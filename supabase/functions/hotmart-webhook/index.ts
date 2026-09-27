/**
 * hotmart-webhook/index.ts
 * ========================
 * Supabase Edge Function — hanterar Hotmart-webhook-events för SEO Brasil.
 *
 * Hanterade events:
 *   PURCHASE_COMPLETE         → plan='pro|premium', subscription_status='active'
 *   PURCHASE_APPROVED         → (synonym) samma som ovan
 *   PURCHASE_REFUNDED         → subscription_status='refunded'
 *   PURCHASE_CHARGEBACK       → subscription_status='chargeback'
 *   PURCHASE_CANCELED         → subscription_status='cancelled'
 *   SUBSCRIPTION_CANCELLATION → subscription_status='cancelled'
 *
 * Hotmart webhook-payload (v2.0.0) — verifierade fält:
 *   data.buyer.email          — köparens e-post (alltid present)
 *   data.offer.code           — offer code (t.ex. "bdwmhc7l")
 *   data.purchase.transaction — unikt transaktions-ID (t.ex. "HP12345678901")
 *                               Saknas ibland för SUBSCRIPTION_CANCELLATION.
 *
 * Autentisering: X-Hotmart-Hottok header (shared secret, ingen HMAC)
 *
 * Idempotency: hotmart_events-tabellen med UNIQUE(transaction_id, event).
 *   Samma transaktion kan ha flera events (PURCHASE_COMPLETE → PURCHASE_REFUNDED).
 *
 * Deploy:
 *   supabase functions deploy hotmart-webhook --no-verify-jwt
 *
 * Secrets (Supabase Dashboard → Edge Functions → Secrets):
 *   HOTMART_HOTTOK        — security key från Hotmart Produtor → Webhooks
 *   HOTMART_OFFER_PRO     — offer code för Pro-planen
 *   HOTMART_OFFER_PREMIUM — offer code för Premium-planen (bdwmhc7l)
 *
 * Sätt webhook-URL i Hotmart:
 *   Produtor → Ferramentas → Webhooks → URL:
 *   https://<project-ref>.supabase.co/functions/v1/hotmart-webhook
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// ---------------------------------------------------------------------------
// Konfiguration — enbart via Supabase Secrets, aldrig hårdkodat
// ---------------------------------------------------------------------------
const SUPABASE_URL    = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY     = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const HOTTOK          = Deno.env.get("HOTMART_HOTTOK") ?? "";
const OFFER_PRO       = Deno.env.get("HOTMART_OFFER_PRO") ?? "";
const OFFER_PREMIUM   = Deno.env.get("HOTMART_OFFER_PREMIUM") ?? "";

// ---------------------------------------------------------------------------
// Hjälpfunktioner
// ---------------------------------------------------------------------------
function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Extraherar ett nästlat värde ur ett okänt JSON-objekt på ett typsäkert sätt.
function get(obj: unknown, ...keys: string[]): unknown {
  let cur: unknown = obj;
  for (const k of keys) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[k];
  }
  return cur;
}

// ---------------------------------------------------------------------------
// Huvud-handler
// ---------------------------------------------------------------------------
Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return jsonResponse(405, { error: "Method not allowed" });
  }

  // ── 1. Autentisering ─────────────────────────────────────────────────────
  // Hotmart använder ett delat secret i X-Hotmart-Hottok-headern.
  // Ingen HMAC — enkel strängkomparation är korrekt metod.
  const receivedHottok = req.headers.get("X-Hotmart-Hottok") ?? "";
  if (!HOTTOK || receivedHottok !== HOTTOK) {
    console.error("Ogiltigt eller saknat X-Hotmart-Hottok");
    return jsonResponse(401, { error: "Unauthorized" });
  }

  // ── 2. Parsa payload ─────────────────────────────────────────────────────
  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return jsonResponse(400, { error: "Invalid JSON" });
  }

  // Hotmart v2.0.0 payload-struktur (verifierade fält):
  //   payload.event                        — event-typ
  //   payload.data.buyer.email             — köparens e-post
  //   payload.data.offer.code              — offer code
  //   payload.data.purchase.transaction    — transaktions-ID (t.ex. "HP12345678901")
  //   payload.creation_date                — Unix-timestamp i ms (fallback för tx-nyckel)
  const event        = String(get(payload, "event") ?? "");
  const email        = String(get(payload, "data", "buyer", "email") ?? "").toLowerCase().trim();
  const offerCode    = String(get(payload, "data", "offer", "code") ?? "");
  const transaction  = String(get(payload, "data", "purchase", "transaction") ?? "");
  const creationDate = String(get(payload, "creation_date") ?? Date.now());

  console.log(`Hotmart event: ${event} | offer: ${offerCode} | email: ${email} | tx: ${transaction}`);

  // ── 3. Filtrera okända events ─────────────────────────────────────────────
  const HANDLED_EVENTS = new Set([
    "PURCHASE_COMPLETE",
    "PURCHASE_APPROVED",
    "PURCHASE_REFUNDED",
    "PURCHASE_CHARGEBACK",
    "PURCHASE_CANCELED",
    "SUBSCRIPTION_CANCELLATION",
  ]);

  if (!HANDLED_EVENTS.has(event)) {
    return jsonResponse(200, { ignored: true, reason: "unknown_event", event });
  }

  // ── 4. Validera e-post ────────────────────────────────────────────────────
  if (!email || !email.includes("@")) {
    console.error("Saknar eller ogiltig buyer.email:", email);
    return jsonResponse(422, { error: "Missing or invalid buyer email" });
  }

  const supabase = createClient(SUPABASE_URL, SERVICE_KEY);

  // ── 5. Idempotency-check (transaction_id + event) ─────────────────────────
  // SUBSCRIPTION_CANCELLATION saknar ibland transaction — bygg en stabil fallback-nyckel.
  const txKey = transaction || `no-tx:${email}:${event}:${creationDate}`;

  const { data: existing, error: checkErr } = await supabase
    .from("hotmart_events")
    .select("id")
    .eq("transaction_id", txKey)
    .eq("event", event)
    .maybeSingle();

  if (checkErr) {
    // Idempotency-check misslyckades — logga men fortsätt (hellre dubbel-process än miss)
    console.error("Idempotency-check misslyckades:", checkErr.message);
  } else if (existing) {
    console.log(`Event redan processat (idempotent): ${txKey} / ${event}`);
    return jsonResponse(200, { ok: true, idempotent: true });
  }

  // ── 6. Bestäm DB-uppdatering baserat på event ────────────────────────────
  const dbUpdate: Record<string, string> = {};

  if (event === "PURCHASE_COMPLETE" || event === "PURCHASE_APPROVED") {
    if (!OFFER_PRO || !OFFER_PREMIUM) {
      console.error("HOTMART_OFFER_PRO eller HOTMART_OFFER_PREMIUM saknas i Secrets");
      return jsonResponse(500, { error: "Offer codes not configured" });
    }

    if (offerCode === OFFER_PREMIUM) {
      dbUpdate.plan = "premium";
    } else if (offerCode === OFFER_PRO) {
      dbUpdate.plan = "pro";
    } else {
      // Okänd offer code — logga och ignorera utan att röra databasen
      console.warn(`Okänd offer code: "${offerCode}" — ignorerar`);
      return jsonResponse(200, { ignored: true, reason: "unknown_offer", offer_code: offerCode });
    }

    dbUpdate.subscription_status = "active";

  } else if (event === "PURCHASE_REFUNDED") {
    dbUpdate.subscription_status = "refunded";

  } else if (event === "PURCHASE_CHARGEBACK") {
    dbUpdate.subscription_status = "chargeback";

  } else if (event === "PURCHASE_CANCELED" || event === "SUBSCRIPTION_CANCELLATION") {
    dbUpdate.subscription_status = "cancelled";
  }

  // ── 7. Uppdatera subscribers ──────────────────────────────────────────────
  const { error: updateErr, count } = await supabase
    .from("subscribers")
    .update(dbUpdate)
    .eq("email", email)
    .select("email", { count: "exact", head: true });

  if (updateErr) {
    console.error("subscribers UPDATE misslyckades:", updateErr.message);
    return jsonResponse(500, { error: "Database update failed" });
  }

  const subscriberFound = (count ?? 0) > 0;
  if (!subscriberFound) {
    // Kunden saknar konto — kan hända om köpet sker innan registrering.
    // Vi loggar ändå händelsen (se steg 8) för att kunna matcha manuellt.
    console.warn(`Ingen subscriber hittad för email: ${email}`);
  }

  // ── 8. Logga processat event (idempotency + audit trail) ─────────────────
  const { error: logErr } = await supabase.from("hotmart_events").insert({
    transaction_id: txKey,
    event,
    email,
    offer_code: offerCode,
    subscriber_found: subscriberFound,
    processed_at: new Date().toISOString(),
  });

  if (logErr && !logErr.message?.includes("duplicate")) {
    // Icke-kritiskt — returnera 200 ändå men logga felet
    console.error("hotmart_events INSERT misslyckades:", logErr.message);
  }

  console.log(
    `✓ Processat: event=${event} | email=${email} | update=${JSON.stringify(dbUpdate)} | found=${subscriberFound}`,
  );

  return jsonResponse(200, {
    ok: true,
    event,
    email,
    plan: dbUpdate.plan ?? null,
    subscription_status: dbUpdate.subscription_status ?? null,
    subscriber_found: subscriberFound,
  });
});
