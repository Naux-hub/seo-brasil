"""
outreach_runner.py
==================

3-stegs outreach-sekvens för SEO Brasil outbound lead pipeline.

Steg:
  1 (Pitch)       — första kontakten, dag 0
  2 (Follow-up 1) — 3 dagar utan svar
  3 (Follow-up 2) — 7 dagar utan svar
  → Stopp          — ingen mer kontakt

Regler:
- DRY_RUN=True som standard — ingen riktig e-post skickas utan --live-flaggan
- Stoppar på: opt_out=TRUE, status IN (responded_positive, responded_negative, opt_out, stopped)
- Personalisering enbart från faktiska lead-datafält (company_name, domain, niche)
  — inga påhittade SEO-problem
- Loggar varje försök (inklusive DRY_RUN) i `lead_outreach_log`-tabellen
- Max 10 leads per körning (pilot-limit, justerbar med --max-leads)
- Tydlig opt-out-länk i varje e-post

Kör:
    python outreach_runner.py --step 1 --dry-run        # simulera pitch
    python outreach_runner.py --step 2 --dry-run        # simulera follow-up 1
    python outreach_runner.py --step 1 --live           # skicka riktiga pitchar

Kräver miljövariabler (eller .env):
    SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY
    SEOBRASIL_OPT_OUT_URL (t.ex. https://seobrasil.app/optout)
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

try:
    import dns.resolver as _dns_resolver
    _HAS_DNSPYTHON = True
except ImportError:
    _HAS_DNSPYTHON = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("outreach_runner")

# ---------------------------------------------------------------------------
# KONFIGURATION
# ---------------------------------------------------------------------------

# Avsändaradress för cold outbound — SEPARERAT från produktmail (oi@seobrasil.app).
# Sätt OUTBOUND_FROM_EMAIL i miljön för att byta adress utan kodändring.
# Rekommenderat: outreach@seobrasil.app eller en dedikerad subdomain.
FROM_EMAIL = os.environ.get(
    "OUTBOUND_FROM_EMAIL",
    "Samuel @ SEO Brasil <outreach@seobrasil.app>",
)
REPLY_TO = os.environ.get("OUTBOUND_REPLY_TO", "outreach@seobrasil.app")

STEP_CONFIG = {
    1: {"email_type": "pitch",        "days_wait": 0,  "status_after": "pitch_sent",  "sequence_step": 1},
    2: {"email_type": "follow_up_1",  "days_wait": 3,  "status_after": "fu1_sent",    "sequence_step": 2},
    3: {"email_type": "follow_up_2",  "days_wait": 7,  "status_after": "fu2_sent",    "sequence_step": 3},
}

PILOT_DAILY_LIMIT = 10  # max leads att kontakta per körning

STOP_STATUSES = {
    "responded_positive", "responded_negative",
    "opt_out", "stopped", "fu2_sent",
    "bounced", "complained",          # leveransfel / spam-rapport
}

# ---------------------------------------------------------------------------
# SAFETY GATE — alla checks måste vara PASS innan ett lead får skickas
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

# Kända disposable/placeholder-domäner
_DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "tempmail.com",
    "throwam.com", "sharklasers.com", "yopmail.com",
    "emailcliente.com", "meu.com", "seuemail.com",
}


def _validate_email_format(email: str) -> bool:
    """Returnerar True om e-postadressen har giltigt format."""
    return bool(_EMAIL_RE.match(email.strip()))


def _check_mx(email: str) -> bool:
    """
    Returnerar True om domänen har minst en MX-post i DNS.
    Kräver dnspython (`pip install dnspython --break-system-packages`).
    Om paketet saknas loggas en varning och kontrollen hoppas över (fail-open
    för MX, men email-format och disposable-check kvarstår).
    """
    if not _HAS_DNSPYTHON:
        logger.warning(
            "dnspython saknas — MX-check hoppas över. "
            "Installera med: pip install dnspython --break-system-packages"
        )
        return True  # fail-open: blockera inte utskick pga saknat paket

    domain = email.split("@")[-1].lower().strip()
    try:
        answers = _dns_resolver.resolve(domain, "MX", lifetime=5)
        return len(answers) > 0
    except Exception:
        return False


def _is_disposable(email: str) -> bool:
    """Returnerar True om domänen finns i listan över disposable-adresser."""
    domain = email.split("@")[-1].lower().strip()
    return domain in _DISPOSABLE_DOMAINS


def safety_gate(lead: dict, to_email: str) -> tuple[bool, str]:
    """
    Kör alla hygien-checks för ett lead innan utskick.

    Returnerar (ok, reason):
      ok=True  → leadet får skickas
      ok=False → leadet ska stoppas; reason anger orsaken för loggning

    Checks (i ordning):
      1. opt_out / STOP_STATUSES          — redan hanteras i main loop
      2. email_format                     — regex
      3. disposable_domain                — blocklista
      4. mx_record                        — DNS MX-lookup
      5. bounced / complained via status  — hanteras via STOP_STATUSES
    """
    # 1. Statuscheck (redundant säkerhet — sker också i main loop)
    if lead.get("opt_out"):
        return False, "opt_out"
    if lead.get("status") in STOP_STATUSES:
        return False, f"stop_status:{lead.get('status')}"

    # 2. Email-format
    if not _validate_email_format(to_email):
        return False, "invalid_email_format"

    # 3. Disposable/placeholder
    if _is_disposable(to_email):
        return False, "disposable_domain"

    # 4. MX-record
    if not _check_mx(to_email):
        return False, "no_mx_record"

    return True, "pass"

OPT_OUT_BASE_URL = os.environ.get("SEOBRASIL_OPT_OUT_URL", "https://seobrasil.app/optout")


# ---------------------------------------------------------------------------
# SUPABASE
# ---------------------------------------------------------------------------

def _supabase_headers(service_key: str) -> dict:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }


def fetch_leads_for_step(
    step: int,
    supabase_url: str,
    service_key: str,
    max_leads: int = PILOT_DAILY_LIMIT,
) -> list[dict]:
    """
    Hämtar kvalificerade leads som är redo för angivet steg.

    Steg 1 (Pitch):
      - status = 'new' eller 'qualified'
      - qualified = TRUE
      - opt_out = FALSE

    Steg 2 (FU1):
      - status = 'pitch_sent'
      - contacted_at <= NOW() - 3 dagar
      - opt_out = FALSE

    Steg 3 (FU2):
      - status = 'fu1_sent'
      - last_contacted_at <= NOW() - 7 dagar
      - opt_out = FALSE
    """
    headers = _supabase_headers(service_key)
    headers["Prefer"] = "return=representation"

    base = f"{supabase_url}/rest/v1/leads"
    now = datetime.now(timezone.utc)

    if step == 1:
        params = {
            "qualified": "eq.true",
            "opt_out":   "eq.false",
            "status":    "in.(new,qualified)",
            "select":    "*",
            "limit":     str(max_leads),
        }
    elif step == 2:
        cutoff = (now - timedelta(days=3)).isoformat()
        params = {
            "status":        "eq.pitch_sent",
            "opt_out":       "eq.false",
            "contacted_at":  f"lte.{cutoff}",
            "select":        "*",
            "limit":         str(max_leads),
        }
    elif step == 3:
        cutoff = (now - timedelta(days=7)).isoformat()
        params = {
            "status":             "eq.fu1_sent",
            "opt_out":            "eq.false",
            "last_contacted_at":  f"lte.{cutoff}",
            "select":             "*",
            "limit":              str(max_leads),
        }
    else:
        raise ValueError(f"Ogiltigt steg: {step}")

    r = requests.get(base, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def update_lead_status(
    lead_id: str,
    step: int,
    supabase_url: str,
    service_key: str,
) -> None:
    """Uppdaterar lead-status och tidsstämplar efter ett utskick."""
    cfg = STEP_CONFIG[step]
    now = datetime.now(timezone.utc).isoformat()

    patch: dict = {
        "status":        cfg["status_after"],
        "sequence_step": cfg["sequence_step"],
        "last_contacted_at": now,
    }
    if step == 1:
        patch["contacted_at"] = now

    r = requests.patch(
        f"{supabase_url}/rest/v1/leads?id=eq.{lead_id}",
        headers=_supabase_headers(service_key),
        json=patch,
        timeout=15,
    )
    r.raise_for_status()


def log_outreach(
    lead_id: str,
    step: int,
    sent_to: str,
    subject: str,
    body_html: str,
    dry_run: bool,
    resend_id: Optional[str],
    supabase_url: str,
    service_key: str,
) -> None:
    """Loggar ett utskick (eller DRY RUN-simulering) i lead_outreach_log."""
    cfg = STEP_CONFIG[step]
    row = {
        "lead_id":    lead_id,
        "step":       step,
        "email_type": cfg["email_type"],
        "sent_to":    sent_to,
        "subject":    subject,
        "body_html":  body_html,
        "dry_run":    dry_run,
        "resend_id":  resend_id,
    }
    r = requests.post(
        f"{supabase_url}/rest/v1/lead_outreach_log",
        headers=_supabase_headers(service_key),
        json=row,
        timeout=15,
    )
    r.raise_for_status()


# ---------------------------------------------------------------------------
# EMAIL-SÄNDNING
#
# BACKEND väljs via miljövariabeln EMAIL_BACKEND:
#   "resend"  (default, nuvarande) — Resend HTTP API
#   "smtp"                         — SMTP-relay (Instantly / Smartlead / annat)
#
# VIKTIGT: Resend förbjuder cold outreach (AUP). Vid volymökning byt till
#          "smtp" med Instantly eller Smartlead som relay-leverantör.
# ---------------------------------------------------------------------------

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "resend")   # "resend" | "smtp"


def send_email(
    to: str,
    subject: str,
    body_html: str,
    resend_api_key: str,
) -> str:
    """
    Skickar e-post via valt backend. Returnerar ett message-ID (str).

    Backend "resend":
      Kräver RESEND_API_KEY.

    Backend "smtp":
      Kräver SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD.
      Kompatibelt med Instantly SMTP-relay och Smartlead SMTP-relay.
    """
    if EMAIL_BACKEND == "smtp":
        return _send_email_smtp(to, subject, body_html)
    else:
        return _send_email_resend(to, subject, body_html, resend_api_key)


def _send_email_resend(to: str, subject: str, body_html: str, api_key: str) -> str:
    """Skickar via Resend HTTP API."""
    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from":     FROM_EMAIL,
            "reply_to": REPLY_TO,
            "to":       [to],
            "subject":  subject,
            "html":     body_html,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("id", "")


def _send_email_smtp(to: str, subject: str, body_html: str) -> str:
    """
    Skickar via SMTP-relay (Instantly / Smartlead / annan leverantör).

    Miljövariabler som krävs:
        SMTP_HOST      t.ex. smtp.instantly.ai  eller  smtp.smartlead.ai
        SMTP_PORT      vanligtvis 587
        SMTP_USER      din SMTP-användare (e-postadress)
        SMTP_PASSWORD  ditt SMTP-lösenord / API-nyckel

    Returnerar ett syntetiskt message-ID (UUID-format).
    """
    import smtplib
    import uuid
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    host     = os.environ.get("SMTP_HOST", "")
    port     = int(os.environ.get("SMTP_PORT", "587"))
    user     = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")

    if not all([host, user, password]):
        raise RuntimeError(
            "SMTP-backend kräver SMTP_HOST, SMTP_USER och SMTP_PASSWORD."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to
    msg["Reply-To"] = REPLY_TO
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to], msg.as_string())

    return f"smtp-{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# EMAIL-MALLAR
# ---------------------------------------------------------------------------

def _opt_out_link(lead_id: str) -> str:
    return f"{OPT_OUT_BASE_URL}?id={lead_id}"


def render_pitch(lead: dict) -> tuple[str, str]:
    """
    Returnerar (subject, body_html) för pitch-e-posten.

    Personalisering (alltid):
      - company_name  → hälsningsfras + ämnesrad
      - domain        → "encontrei o site {domain}"
      - opt-out-länk  → unik per lead (lead_id)

    Konditionell personalisering (bara när verifierat av scraper):
      - missing_title=True och/eller missing_meta=True →
        ett extra faktapåstående om den faktiska bristen.
        Påståendet görs ALDRIG om scraper-data saknas eller är False.
    """
    name    = lead.get("company_name") or "Olá"
    domain  = lead.get("domain") or lead.get("lead_url") or ""
    opt_out = _opt_out_link(lead["id"])

    subject = (
        f"Dúvida rápida sobre {name} no Google 🔍"
        if name != "Olá"
        else "Dúvida rápida sobre seu site no Google 🔍"
    )

    # ── Konditionell SEO-mening (baseras ENBART på verifierade scraper-fält) ──
    missing_title = lead.get("missing_title") is True
    missing_meta  = lead.get("missing_meta")  is True

    if missing_title and missing_meta:
        seo_elements = "title tag e meta description"
    elif missing_title:
        seo_elements = "title tag"
    elif missing_meta:
        seo_elements = "meta description"
    else:
        seo_elements = None

    if seo_elements:
        # Faktabaserat påstående — formulerat som observation, inte attack
        seo_sentence = (
            f"<p>Passando aqui porque notamos que o site <strong>{domain}</strong> "
            f"está sem {seo_elements} — "
            f"fatores que o Google usa para entender e rankear páginas.</p>"
        )
        intro_paragraph = seo_sentence
    else:
        intro_paragraph = (
            f"<p>Passei aqui porque encontrei o site <strong>{domain}</strong> e fiquei curioso: "
            f"quando um cliente em potencial pesquisa pelo que vocês vendem no Google, o site aparece?</p>"
        )

    body_html = f"""
<p>Oi {name}, tudo bem?</p>

{intro_paragraph}

<p>Criamos o <strong>SEO Brasil</strong> — uma ferramenta de pesquisa de palavras-chave
focada 100% no mercado brasileiro. Com ela você descobre:</p>

<ul>
  <li>Quais termos seus clientes digitam antes de comprar</li>
  <li>Volume de busca mensal e nível de concorrência</li>
  <li>Todo início de semana, um relatório automático no e-mail — incluindo sugestões de o que otimizar</li>
</ul>

<p>Você pode testar de graça em: <a href="https://seobrasil.app">seobrasil.app</a></p>

<p>O plano é R$197/mês — menos do que um dia de anúncio no Meta.</p>

<p>Qualquer dúvida, é só responder aqui. 👊</p>

<p>Abraço,<br>Samuel<br>
<a href="https://seobrasil.app">seobrasil.app</a></p>

<p style="font-size:11px;color:#888;">
Você recebeu este e-mail porque encontramos seu site publicamente.
<a href="{opt_out}">Clique aqui para não receber mais mensagens.</a>
</p>
""".strip()

    return subject, body_html


def render_follow_up_1(lead: dict) -> tuple[str, str]:
    """Follow-up 1 — kort, sem pressão, 3 dagar efter pitch."""
    name = lead.get("company_name") or "Olá"
    opt_out = _opt_out_link(lead["id"])

    subject = "Re: SEO Brasil — só passando para ver 😊"

    body_html = f"""
<p>Oi {name}!</p>

<p>Só passando para ver se você teve chance de dar uma olhada na mensagem que mandei
sobre o SEO Brasil. Sem pressão — só queria saber se faz sentido para o seu negócio.</p>

<p>Se tiver qualquer dúvida, é só responder aqui.</p>

<p>Abraço,<br>Samuel<br>
<a href="https://seobrasil.app">seobrasil.app</a></p>

<p style="font-size:11px;color:#888;">
<a href="{opt_out}">Clique aqui para não receber mais mensagens.</a>
</p>
""".strip()

    return subject, body_html


def render_follow_up_2(lead: dict) -> tuple[str, str]:
    """Follow-up 2 — social proof / ROI-vinkel, 7 dagar efter pitch."""
    name = lead.get("company_name") or "Olá"
    opt_out = _opt_out_link(lead["id"])

    subject = "Última mensagem — SEO Brasil"

    body_html = f"""
<p>Oi {name},</p>

<p>Promessa: última mensagem sobre o SEO Brasil. 😊</p>

<p>Nossos clientes usam a ferramenta para descobrir quais palavras-chave
seus concorrentes estão ranqueando — e então focam o conteúdo nessas oportunidades.
É a diferença entre adivinhar e saber.</p>

<p>Se quiser testar antes de qualquer compromisso:
<a href="https://seobrasil.app">seobrasil.app</a> — acesso gratuito disponível.</p>

<p>Caso não seja o momento certo, tudo bem! Fica à vontade para voltar quando fizer sentido.</p>

<p>Abraço,<br>Samuel<br>
<a href="https://seobrasil.app">seobrasil.app</a></p>

<p style="font-size:11px;color:#888;">
<a href="{opt_out}">Clique aqui para não receber mais mensagens.</a>
</p>
""".strip()

    return subject, body_html


RENDERERS = {
    1: render_pitch,
    2: render_follow_up_1,
    3: render_follow_up_2,
}


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------

def run_outreach(
    step: int,
    supabase_url: str,
    service_key: str,
    resend_api_key: str,
    dry_run: bool = True,
    max_leads: int = PILOT_DAILY_LIMIT,
) -> dict:
    """
    Kör ett steg i outreach-sekvensen för alla leads som är redo.
    Returnerar statistik.
    """
    stats = {"sent": 0, "skipped_no_contact": 0, "errors": 0, "dry_run": dry_run}

    leads = fetch_leads_for_step(step, supabase_url, service_key, max_leads=max_leads)
    logger.info(
        "Steg %d: Hittade %d leads redo för utskick (dry_run=%s)",
        step, len(leads), dry_run,
    )

    renderer = RENDERERS[step]

    for lead in leads:
        lead_id = lead["id"]

        # Stoppa omedelbart om opt_out eller avslutat status
        if lead.get("opt_out") or lead.get("status") in STOP_STATUSES:
            logger.info("Hoppar över (stoppad): %s", lead_id)
            continue

        # Hämta mottagarens e-post
        to_email = None
        if lead.get("contact_type") == "email" and lead.get("contact_info"):
            to_email = lead["contact_info"]

        if not to_email:
            logger.warning(
                "Ingen e-postadress för lead %s (domain=%s) — hoppar över.",
                lead_id, lead.get("domain"),
            )
            stats["skipped_no_contact"] += 1
            continue

        # ── Safety gate ──────────────────────────────────────────────────────
        ok, reason = safety_gate(lead, to_email)
        if not ok:
            logger.warning(
                "Safety gate FAIL [%s]: lead=%s email=%s — hoppar över.",
                reason, lead_id, to_email,
            )
            stats.setdefault("skipped_safety_gate", 0)
            stats["skipped_safety_gate"] += 1
            continue
        # ─────────────────────────────────────────────────────────────────────

        subject, body_html = renderer(lead)

        if dry_run:
            logger.info(
                "[DRY RUN] Steg %d → %s | subject: %s",
                step, to_email, subject,
            )
            logger.info("  body_html (preview):\n%s", body_html[:400])
            # Logga i DB också (dry_run=TRUE)
            try:
                log_outreach(
                    lead_id, step, to_email, subject, body_html,
                    dry_run=True, resend_id=None,
                    supabase_url=supabase_url, service_key=service_key,
                )
            except Exception as e:
                logger.warning("Kunde inte logga DRY RUN i DB: %s", e)
            stats["sent"] += 1
            continue

        # Live-läge
        try:
            resend_id = send_email(to_email, subject, body_html, resend_api_key)
            log_outreach(
                lead_id, step, to_email, subject, body_html,
                dry_run=False, resend_id=resend_id,
                supabase_url=supabase_url, service_key=service_key,
            )
            update_lead_status(lead_id, step, supabase_url, service_key)
            logger.info("Skickad (%s): %s → %s", STEP_CONFIG[step]["email_type"], lead_id, to_email)
            stats["sent"] += 1
        except Exception as e:
            logger.error("Fel vid utskick för %s (%s): %s", lead_id, to_email, e)
            stats["errors"] += 1

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kör ett steg i SEO Brasil outreach-sekvensen (1=Pitch, 2=FU1, 3=FU2)."
    )
    parser.add_argument(
        "--step", type=int, required=True, choices=[1, 2, 3],
        help="Vilket steg att köra: 1=Pitch, 2=Follow-up 1, 3=Follow-up 2.",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Kör live-läge (skickar riktiga e-postmeddelanden). Default är DRY RUN.",
    )
    parser.add_argument(
        "--max-leads", type=int, default=PILOT_DAILY_LIMIT,
        help=f"Max antal leads att kontakta per körning (default: {PILOT_DAILY_LIMIT}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dry_run = not args.live

    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key  = os.environ.get("SUPABASE_SERVICE_KEY", "")
    resend_key   = os.environ.get("RESEND_API_KEY", "")

    if not supabase_url or not service_key:
        logger.error("SUPABASE_URL och SUPABASE_SERVICE_KEY krävs som miljövariabler.")
        sys.exit(1)

    if not dry_run and not resend_key:
        logger.error("RESEND_API_KEY krävs för --live.")
        sys.exit(1)

    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info("Startar steg %d [%s] (max %d leads)", args.step, mode, args.max_leads)

    stats = run_outreach(
        step=args.step,
        supabase_url=supabase_url,
        service_key=service_key,
        resend_api_key=resend_key,
        dry_run=dry_run,
        max_leads=args.max_leads,
    )

    logger.info(
        "Klart [%s]: %d skickade | %d utan e-post | %d safety-gate | %d fel",
        mode, stats["sent"], stats["skipped_no_contact"],
        stats.get("skipped_safety_gate", 0), stats["errors"],
    )


if __name__ == "__main__":
    main()
