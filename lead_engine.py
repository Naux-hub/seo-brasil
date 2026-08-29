"""
lead_engine.py
==============

Scoring-modul + Supabase DB-import för SEO Brasil outbound lead pipeline.

Tar emot leads från valfri scraper, beräknar en poäng per lead baserat på
faktiska datafält, och skriver kvalificerade leads till Supabase `leads`-tabellen.

Scoring (konservativ — hellre 10 bra leads än 40 dåliga):
  +3  har eget domän
  +2  har e-postadress
  +2  plattform = Shopify eller Loja Integrada
  +1  saknar meta description (konkret SEO-brist)
  +1  saknar title-tag (konkret SEO-brist)
  +1  nisch klassad som hög relevans

  Kvalificerad (qualified=TRUE) om score >= 4.

Användning som modul:
    from lead_engine import score_lead, LeadData, upsert_leads

Användning som CLI:
    python lead_engine.py --json-file leads.json --source br_ecommerce --campaign "roupas_2026-08-25"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("lead_engine")

# ---------------------------------------------------------------------------
# KONFIGURATION
# ---------------------------------------------------------------------------

QUALIFIED_THRESHOLD = 4   # poäng för att markeras som qualified=TRUE

HIGH_RELEVANCE_NICHES = {
    "suplementos", "moda", "beleza", "esportes", "fitness",
    "saude", "saúde", "roupas", "calcados", "calçados",
    "cosmeticos", "cosméticos", "acessorios", "acessórios",
}

QUALIFYING_PLATFORMS = {"shopify", "loja integrada"}


# ---------------------------------------------------------------------------
# DATAMODELL
# ---------------------------------------------------------------------------

@dataclass
class LeadData:
    """
    Normaliserad leadstruktur — gemensam ingångspunkt för alla scrapers.
    Fyll i de fält du har; resten lämnas None.
    """
    # Obligatoriskt
    source: str                          # 'mercadolivre' | 'br_ecommerce' | 'hotmart' | 'youtube'

    # Lead-info
    lead_url: Optional[str] = None       # ML-butiks-URL eller sajt-URL
    company_name: Optional[str] = None   # butiksnamn / kanalnamn
    domain: Optional[str] = None         # eget domän t.ex. "integralmedica.com.br"
    platform: Optional[str] = None       # 'Shopify' | 'Loja Integrada' | None
    niche: Optional[str] = None          # nisch-nyckelord som scriptet kördes med

    # Kontakt
    contact_info: Optional[str] = None   # e-post, Instagram-URL eller WhatsApp
    contact_type: Optional[str] = None   # 'email' | 'instagram' | 'whatsapp'
    contact_source: Optional[str] = None # var kontakten hittades

    # SEO-brister (från scraper-audit)
    missing_title: Optional[bool] = None
    missing_h1: Optional[bool] = None
    missing_meta: Optional[bool] = None

    # Kampanj
    campaign: Optional[str] = None

    # Rådata (sparas för spårbarhet, används INTE i personalisering)
    raw_data: Optional[dict] = None


@dataclass
class ScoredLead:
    """LeadData + poängresultat."""
    lead: LeadData
    score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    qualified: bool = False


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------

def score_lead(lead: LeadData) -> ScoredLead:
    """
    Beräknar leadets poäng baserat på faktiska datafält.
    Returnerar ett ScoredLead med score, score_breakdown och qualified.
    """
    breakdown: dict[str, int] = {}
    total = 0

    # +3 om eget domän finns
    if lead.domain and lead.domain.strip():
        breakdown["has_domain"] = 3
        total += 3

    # +2 om e-postadress finns (contact_type='email' ELLER contact_info ser ut som e-post)
    has_email = (
        lead.contact_type == "email"
        or (lead.contact_info and "@" in lead.contact_info)
    )
    if has_email:
        breakdown["has_email"] = 2
        total += 2

    # +2 om Shopify eller Loja Integrada (SEO-medvetna plattformar)
    if lead.platform and lead.platform.lower() in QUALIFYING_PLATFORMS:
        breakdown["qualifying_platform"] = 2
        total += 2

    # +1 om saknar meta description
    if lead.missing_meta is True:
        breakdown["missing_meta"] = 1
        total += 1

    # +1 om saknar title-tag
    if lead.missing_title is True:
        breakdown["missing_title"] = 1
        total += 1

    # +1 om nischen är klassad som hög relevans
    if lead.niche:
        niche_normalized = lead.niche.lower().strip()
        if any(h in niche_normalized for h in HIGH_RELEVANCE_NICHES):
            breakdown["high_relevance_niche"] = 1
            total += 1

    qualified = total >= QUALIFIED_THRESHOLD

    return ScoredLead(
        lead=lead,
        score=total,
        score_breakdown=breakdown,
        qualified=qualified,
    )


# ---------------------------------------------------------------------------
# SUPABASE UPSERT
# ---------------------------------------------------------------------------

def upsert_leads(
    scored_leads: list[ScoredLead],
    supabase_url: str,
    supabase_service_key: str,
    dry_run: bool = True,
) -> dict:
    """
    Skriver leads till Supabase `leads`-tabellen via REST API.

    Använder ON CONFLICT (domain) DO NOTHING för att undvika dubbletter —
    samma domän kontaktas aldrig två gånger.

    Returnerar dict med antal insatta / hoppade över / felaktiga.
    """
    stats = {"inserted": 0, "skipped_unqualified": 0, "skipped_duplicate": 0, "errors": 0}

    headers = {
        "apikey": supabase_service_key,
        "Authorization": f"Bearer {supabase_service_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=ignore-duplicates",
    }
    endpoint = f"{supabase_url}/rest/v1/leads"

    for sl in scored_leads:
        if not sl.qualified:
            stats["skipped_unqualified"] += 1
            logger.debug(
                "Ej kvalificerad (score=%d): %s",
                sl.score, sl.lead.domain or sl.lead.lead_url,
            )
            continue

        row = {
            "source":          sl.lead.source,
            "campaign":        sl.lead.campaign,
            "lead_url":        sl.lead.lead_url,
            "company_name":    sl.lead.company_name,
            "domain":          sl.lead.domain,
            "platform":        sl.lead.platform,
            "contact_info":    sl.lead.contact_info,
            "contact_type":    sl.lead.contact_type,
            "contact_source":  sl.lead.contact_source,
            "score":           sl.score,
            "score_breakdown": sl.score_breakdown,
            "qualified":       sl.qualified,
            "missing_title":   sl.lead.missing_title,
            "missing_h1":      sl.lead.missing_h1,
            "missing_meta":    sl.lead.missing_meta,
            "status":          "new",
            "raw_data":        sl.lead.raw_data,
        }

        if dry_run:
            logger.info(
                "[DRY RUN] Skulle infoga lead: domain=%s score=%d breakdown=%s",
                sl.lead.domain, sl.score, sl.score_breakdown,
            )
            stats["inserted"] += 1
            continue

        try:
            r = requests.post(endpoint, headers=headers, json=row, timeout=15)
            if r.status_code in (200, 201):
                stats["inserted"] += 1
                logger.info("Infogad: %s (score=%d)", sl.lead.domain, sl.score)
            elif r.status_code == 409 or (r.status_code == 200 and not r.text.strip()):
                # IGNORE-duplicates returnerar 200 med tom body för konflikter
                stats["skipped_duplicate"] += 1
                logger.debug("Dubblett (redan i DB): %s", sl.lead.domain)
            else:
                stats["errors"] += 1
                logger.error(
                    "Supabase-fel för %s: HTTP %s — %s",
                    sl.lead.domain, r.status_code, r.text[:200],
                )
        except Exception as e:
            stats["errors"] += 1
            logger.error("Nätverksfel för %s: %s", sl.lead.domain, e)

    return stats


# ---------------------------------------------------------------------------
# HJÄLPFUNKTION: konvertera scraper-output till LeadData
# ---------------------------------------------------------------------------

def from_br_ecommerce_record(record: dict, niche: str = "", campaign: str = "") -> LeadData:
    """
    Konverterar en rad från br_ecommerce_lead_scraper till LeadData.
    Förväntade nycklar: domain, platform, email, instagram,
    missing_title, missing_h1, missing_meta.
    """
    email = record.get("email") or record.get("E-post")
    instagram = record.get("instagram") or record.get("Instagram")
    domain = record.get("domain") or record.get("Domän")

    contact_info = email or instagram
    contact_type = "email" if email else ("instagram" if instagram else None)

    return LeadData(
        source="br_ecommerce",
        domain=_clean_domain(domain),
        lead_url=domain,
        platform=record.get("platform") or record.get("Plattform"),
        contact_info=contact_info,
        contact_type=contact_type,
        contact_source="website_homepage",
        missing_title=_to_bool(record.get("missing_title") or record.get("Saknar_Title")),
        missing_h1=_to_bool(record.get("missing_h1") or record.get("Saknar_H1")),
        missing_meta=_to_bool(record.get("missing_meta") or record.get("Saknar_MetaDescription")),
        niche=niche,
        campaign=campaign,
        raw_data=record,
    )


def from_ml_seller(record: dict, niche: str = "", campaign: str = "") -> LeadData:
    """
    Konverterar en rad från mercadolivre_seller_scraper (eller enrich_leads.py)
    till LeadData.

    Hanterar både original ML-scraper-format och enrichat format:
      - Original: store_name, ml_store_url, domain, whatsapp, instagram
      - Enrichat:  + email, platform, missing_title, missing_h1, missing_meta
    """
    email     = record.get("email")
    whatsapp  = record.get("whatsapp")
    instagram = record.get("instagram")

    contact_info = email or whatsapp or instagram
    contact_type = ("email"     if email     else
                    "whatsapp"  if whatsapp  else
                    "instagram" if instagram else None)
    contact_source = record.get("contact_source", "ml_profile")

    return LeadData(
        source="mercadolivre",
        domain=_clean_domain(record.get("domain")),
        lead_url=record.get("ml_store_url") or record.get("ml_url"),
        company_name=record.get("store_name") or record.get("company_name"),
        platform=record.get("platform"),
        contact_info=contact_info,
        contact_type=contact_type,
        contact_source=contact_source,
        missing_title=_to_bool(record.get("missing_title")),
        missing_h1=_to_bool(record.get("missing_h1")),
        missing_meta=_to_bool(record.get("missing_meta")),
        niche=niche,
        campaign=campaign,
        raw_data=record,
    )


def from_hotmart_affiliate(record: dict, niche: str = "", campaign: str = "") -> LeadData:
    """
    Konverterar en rad från hotmart_affiliate_scraper till LeadData.
    Förväntade nycklar: domain, email, instagram, linkedin.
    """
    email = record.get("email") or record.get("Hittad_Epost")
    instagram = record.get("instagram") or record.get("Instagram_Länk")
    domain = record.get("domain") or record.get("Domän")

    contact_info = email or instagram
    contact_type = "email" if email else ("instagram" if instagram else None)

    return LeadData(
        source="hotmart",
        domain=_clean_domain(domain),
        lead_url=domain,
        contact_info=contact_info,
        contact_type=contact_type,
        contact_source="website_homepage",
        niche=niche,
        campaign=campaign,
        raw_data=record,
    )


def _clean_domain(raw: Optional[str]) -> Optional[str]:
    """Tar bort schema och www. för konsekvent deduplicering."""
    if not raw:
        return None
    d = raw.strip().lower()
    for prefix in ("https://www.", "http://www.", "https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
            break
    # Strippa även bart www.-prefix (utan schema)
    if d.startswith("www."):
        d = d[4:]
    return d.rstrip("/") or None


def _to_bool(val) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes", "ja", "x")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scoring + Supabase-import för SEO Brasil lead pipeline."
    )
    parser.add_argument(
        "--json-file", required=True,
        help="JSON-fil med lista av lead-objekt (output från en scraper).",
    )
    parser.add_argument(
        "--source", required=True,
        choices=["br_ecommerce", "mercadolivre", "hotmart", "youtube"],
        help="Vilken scraper datan kommer ifrån.",
    )
    parser.add_argument(
        "--niche", default="",
        help="Nisch-nyckelord (används för relevanspoäng).",
    )
    parser.add_argument(
        "--campaign", default="",
        help='Kampanjnamn, t.ex. "ml_suplementos_2026-08-25".',
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Simulera utan att skriva till Supabase (default: True).",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Kör live-läge (skriver till Supabase). Kräver SUPABASE_URL och SUPABASE_SERVICE_KEY.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dry_run = not args.live

    with open(args.json_file, encoding="utf-8") as f:
        raw_records: list[dict] = json.load(f)

    logger.info("Läste %d rader från %s", len(raw_records), args.json_file)

    converters = {
        "br_ecommerce":  from_br_ecommerce_record,
        "mercadolivre":  from_ml_seller,
        "hotmart":       from_hotmart_affiliate,
    }
    converter = converters.get(args.source)
    if not converter:
        logger.error("Ingen konverterare för source '%s'.", args.source)
        sys.exit(1)

    leads = [converter(r, niche=args.niche, campaign=args.campaign) for r in raw_records]
    scored = [score_lead(l) for l in leads]

    # Visa poängsättning
    qualified_count = sum(1 for s in scored if s.qualified)
    logger.info(
        "Poängsättning klar: %d leads totalt, %d kvalificerade (score >= %d)",
        len(scored), qualified_count, QUALIFIED_THRESHOLD,
    )

    for s in scored:
        marker = "✓" if s.qualified else "✗"
        logger.info(
            "  %s score=%d breakdown=%s domain=%s",
            marker, s.score, s.score_breakdown,
            s.lead.domain or s.lead.lead_url or "—",
        )

    # DB-import
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    if not dry_run and (not supabase_url or not supabase_key):
        logger.error("SUPABASE_URL och SUPABASE_SERVICE_KEY krävs för --live.")
        sys.exit(1)

    stats = upsert_leads(scored, supabase_url, supabase_key, dry_run=dry_run)

    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info(
        "[%s] Klart: %d infogade | %d ej kvalificerade | %d dubbletter | %d fel",
        mode, stats["inserted"], stats["skipped_unqualified"],
        stats["skipped_duplicate"], stats["errors"],
    )


if __name__ == "__main__":
    main()
