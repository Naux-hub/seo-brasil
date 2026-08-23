/**
 * unsubscribe/index.ts
 * Supabase Edge Function — avregistrering från marketing-emails.
 *
 * Flöde:
 *   GET /functions/v1/unsubscribe?token=<TOKEN>
 *   1. Slå upp token → user_id i unsubscribe_tokens
 *   2. Infoga (user_id, day=0) i onboarding_emails → blockerar framtida utskick
 *   3. Returnera HTML-bekräftelsesida
 *
 * Kräver inga cookies eller inloggning.
 * Idempotent: flera klick ger samma resultat.
 *
 * Deploy:
 *   supabase functions deploy unsubscribe
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

// ── HTML-sidor ────────────────────────────────────────────────────────────────

function pageSuccess(): string {
  return `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SEO Brasil — Cancelamento confirmado</title>
  <style>
    body { margin: 0; background: #0e0e0e; font-family: Arial, sans-serif;
           display: flex; align-items: center; justify-content: center;
           min-height: 100vh; }
    .card { background: #1a1a1a; border-radius: 12px; padding: 40px 48px;
            max-width: 480px; text-align: center; }
    h1 { color: white; font-size: 22px; margin: 0 0 12px; }
    p  { color: #9CA3AF; font-size: 15px; line-height: 1.6; margin: 0 0 24px; }
    a  { color: #4d9fff; font-size: 14px; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .icon { font-size: 40px; margin-bottom: 16px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <h1>Cancelamento confirmado</h1>
    <p>
      Você não receberá mais e-mails de onboarding do SEO Brasil.<br>
      Sua conta e acesso à ferramenta continuam ativos normalmente.
    </p>
    <a href="https://seobrasil.app">Voltar para o SEO Brasil</a>
  </div>
</body>
</html>`;
}

function pageError(message: string): string {
  return `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SEO Brasil — Erro</title>
  <style>
    body { margin: 0; background: #0e0e0e; font-family: Arial, sans-serif;
           display: flex; align-items: center; justify-content: center;
           min-height: 100vh; }
    .card { background: #1a1a1a; border-radius: 12px; padding: 40px 48px;
            max-width: 480px; text-align: center; }
    h1 { color: white; font-size: 22px; margin: 0 0 12px; }
    p  { color: #9CA3AF; font-size: 15px; line-height: 1.6; margin: 0 0 24px; }
    a  { color: #4d9fff; font-size: 14px; text-decoration: none; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Link inválido</h1>
    <p>${message}</p>
    <a href="mailto:oi@seobrasil.app">Entrar em contato</a>
  </div>
</body>
</html>`;
}

function htmlResponse(status: number, body: string): Response {
  // Blob sätter Content-Type från typen snarare än headers,
  // vilket är mer robust mot gateway-manipulation.
  const blob = new Blob([body], { type: "text/html; charset=utf-8" });
  return new Response(blob, { status });
}

// ── Handler ───────────────────────────────────────────────────────────────────

Deno.serve(async (req: Request) => {
  // Acceptera bara GET
  if (req.method !== "GET") {
    return htmlResponse(405, pageError("Método não permitido."));
  }

  const url = new URL(req.url);
  const token = url.searchParams.get("token");

  if (!token || token.length < 10) {
    return htmlResponse(400, pageError("Token inválido ou ausente."));
  }

  // 1. Slå upp token → user_id (logga INTE token-värdet)
  const { data: tokenRows, error: tokenErr } = await supabase
    .from("unsubscribe_tokens")
    .select("user_id")
    .eq("token", token)
    .limit(1);

  if (tokenErr || !tokenRows?.length) {
    return htmlResponse(
      400,
      pageError("Link inválido ou expirado. Se você quiser cancelar, entre em contato conosco."),
    );
  }

  const user_id = tokenRows[0].user_id;

  // 2. Sätt day=0 → blockerar framtida emails (idempotent: insert ignoreras om rad finns)
  const { error: insertErr } = await supabase
    .from("onboarding_emails")
    .insert({ user_id, day: 0 });

  // Ignorera "duplicate" fel — idempotency
  if (insertErr && !insertErr.message?.includes("duplicate")) {
    console.error("insert onboarding_emails error:", insertErr.code);
    return htmlResponse(
      500,
      pageError("Erro interno. Tente novamente ou entre em contato."),
    );
  }

  // 3. Bekräftelsesida
  return htmlResponse(200, pageSuccess());
});
