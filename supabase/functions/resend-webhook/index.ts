/**
 * resend-webhook/index.ts
 * =======================
 * Supabase Edge Function — tar emot Resend-webhooks och uppdaterar
 * leads-tabellen med bounce/complaint-status.
 *
 * Driftsätt:
 *   supabase functions deploy resend-webhook --no-verify-jwt
 *
 * Sätt i Supabase Dashboard → Settings → Edge Functions → Secrets:
 *   RESEND_WEBHOOK_SECRET   (från Resend → Webhooks → Signing secret)
 *   SUPABASE_SERVICE_ROLE_KEY
 *
 * Sätt i Resend → Webhooks → New endpoint:
 *   URL:    https://<project-ref>.supabase.co/functions/v1/resend-webhook
 *   Events: email.bounced, email.complained
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL  = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY   = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const WEBHOOK_SECRET = Deno.env.get("RESEND_WEBHOOK_SECRET") ?? "";

// ---------------------------------------------------------------------------
// Signaturverifiering (HMAC-SHA256)
// ---------------------------------------------------------------------------
async function verifySignature(
  body: string,
  svixId: string,
  svixTs: string,
  svixSig: string,
  secret: string,
): Promise<boolean> {
  if (!secret) return true; // Tillåt utan verifiering i dev-läge

  const toSign   = `${svixId}.${svixTs}.${body}`;
  const keyData  = new TextEncoder().encode(secret.replace(/^whsec_/, ""));
  const msgData  = new TextEncoder().encode(toSign);

  // Decode base64 secret
  const rawKey = Uint8Array.from(atob(new TextDecoder().decode(keyData)), c => c.charCodeAt(0));
  const cryptoKey = await crypto.subtle.importKey(
    "raw", rawKey, { name: "HMAC", hash: "SHA-256" }, false, ["verify"]
  );

  // Resend kan skicka flera signaturer (kommaavskilda)
  for (const sig of svixSig.split(" ")) {
    const sigBytes = Uint8Array.from(atob(sig.replace(/^v1,/, "")), c => c.charCodeAt(0));
    const ok = await crypto.subtle.verify("HMAC", cryptoKey, sigBytes, msgData);
    if (ok) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Huvud-handler
// ---------------------------------------------------------------------------
Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const body     = await req.text();
  const svixId   = req.headers.get("svix-id")        ?? "";
  const svixTs   = req.headers.get("svix-timestamp")  ?? "";
  const svixSig  = req.headers.get("svix-signature")  ?? "";

  // Verifiera signatur
  if (WEBHOOK_SECRET) {
    const valid = await verifySignature(body, svixId, svixTs, svixSig, WEBHOOK_SECRET);
    if (!valid) {
      console.error("Ogiltig webhook-signatur");
      return new Response("Unauthorized", { status: 401 });
    }
  }

  let event: Record<string, unknown>;
  try {
    event = JSON.parse(body);
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  const type = event.type as string;
  console.log(`Resend event: ${type}`);

  // Mappa event-typ till lead-status
  let newStatus: string | null = null;
  if (type === "email.bounced")    newStatus = "bounced";
  if (type === "email.complained") newStatus = "complained";

  if (!newStatus) {
    // Ignorera övriga event-typer
    return new Response(JSON.stringify({ ignored: true }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  // Hämta mottagarens e-post från eventet
  const data      = (event.data ?? {}) as Record<string, unknown>;
  const toEmail   = (data.to as string[] | undefined)?.[0] ?? (data.email as string | undefined);

  if (!toEmail) {
    console.error("Inget e-postfält i event:", JSON.stringify(data));
    return new Response("Missing email", { status: 422 });
  }

  // Uppdatera leads-tabellen
  const supabase = createClient(SUPABASE_URL, SERVICE_KEY);

  const { error, count } = await supabase
    .from("leads")
    .update({ status: newStatus, opt_out: newStatus === "bounced" ? false : true })
    .eq("contact_info", toEmail)
    .neq("status", newStatus)  // Idempotent — uppdatera inte om redan satt
    .select("id", { count: "exact", head: true });

  if (error) {
    console.error("Supabase-fel:", error.message);
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  console.log(`Uppdaterade ${count ?? 0} lead(s) till status=${newStatus} för ${toEmail}`);

  return new Response(
    JSON.stringify({ ok: true, status: newStatus, email: toEmail, updated: count }),
    { headers: { "Content-Type": "application/json" } },
  );
});
