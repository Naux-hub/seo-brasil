"""
affiliate/score_model.py
========================
Affiliate Score v1.2 — SEO Brasil
Source of truth for scoring weights, criteria, and classification.

LOCKED: v1.2 is the official scoring model. Do NOT change weights, point
values, levels, or rules without explicit user approval and a new version bump.
No further calibration until real outreach/conversion data is available.
This file is intentionally isolated so the scorer can be rebuilt around it.

Changelog v1.1 (vs v1.0):
  - target_audience_fit: Added LOCAL_SEO_CAP rule — if candidate primarily
    serves local businesses (not SEO professionals/agencies), cap score at 20/30.
  - customer_volume_potential: Added AGENCY_FLOOR rule — if candidate is an
    SEO agency/consultant with ≥5 employees OR an explicitly mentioned active
    client base, minimum score is 4/10 even without published numbers.
  - purchase_influence: Sharpened evidence requirement — role alone is NOT
    sufficient for levels 13/15. Observable evidence required; otherwise max 5/15.

Changelog v1.2 (vs v1.1):
  - purchase_influence: Replaced old level structure with 5 cleaner levels
    (5/8/10/13/15) with explicit evidence thresholds.
    New level 8/15: strong professional indication (documented client work)
    but no directly observed tool recommendation. Job title ALONE is not
    sufficient for 8/15 — documented professional client/project operations
    must be verifiable.
"""

SCORE_MODEL = {
    "version": "1.2",
    "total_points": 100,
    "categories": [
        {
            "id": "target_audience_fit",
            "name": "Målgruppsfit",
            "emoji": "🎯",
            "max_points": 30,
            "rule": (
                "Bedöm vem personen FAKTISKT når — inte vem de teoretiskt skulle kunna nå. "
                "Insufficient evidence → sätt max 20/30. "
                "LOCAL_SEO_CAP: Om kandidaten primärt hjälper LOKALA FÖRETAG att ranka "
                "(inte SEO-professionella, konsulter eller byråer) → sätt max 20/30 oavsett "
                "övriga signaler. Markera local_seo_cap: true i evidence."
            ),
            "levels": [
                {
                    "points": 30,
                    "description": (
                        "Perfekt match. Personen når exakt SEO Brasil-kunden: brasilianska "
                        "SEO-konsulter, SEO-byråer, SEO-freelancers eller andra som arbetar "
                        "direkt med SEO för brasilianska företag/kunder."
                    ),
                },
                {
                    "points": 25,
                    "description": (
                        "Mycket stark match. Tydligt SEO-fokuserad målgrupp i Brasilien, "
                        "men något bredare — t.ex. digital marketing-professionals där SEO "
                        "är en central del."
                    ),
                },
                {
                    "points": 20,
                    "description": (
                        "Bra match. Relevant brasiliansk marketing-/business-publik där SEO "
                        "är tydlig men inte dominerande."
                    ),
                },
                {
                    "points": 10,
                    "description": (
                        "Svag match. Stor eller relevant publik, men begränsad koppling till "
                        "SEO eller till personer som faktiskt kan köpa SEO Brasil."
                    ),
                },
                {
                    "points": 0,
                    "description": (
                        "Ingen relevant match. Målgruppen är inte relevant för SEO Brasil, "
                        "även om personen har stor räckvidd."
                    ),
                },
            ],
            "observable_signals": [
                "Vilka följer personen?",
                "Vilka är kunderna?",
                "Vilket innehåll produceras?",
                "Vilka problem adresseras?",
                "Är publiken brasiliansk?",
                "Är publiken SEO-professionell?",
                "Finns företag/marknadsförare som faktiskt köper SEO-tjänster?",
                "LOCAL_SEO_CAP: Riktar sig kandaten till lokala småföretag (restauranger, "
                "tandläkare, hantverkare) snarare än till SEO-byråer/konsulter/proffs?",
            ],
        },
        {
            "id": "seo_relevance",
            "name": "SEO-relevans",
            "emoji": "🔎",
            "max_points": 20,
            "rule": (
                "Bedöm om SEO är centralt för personens verksamhet/innehåll. "
                "Basera på observerbara signaler — profilbeskrivning, senaste innehåll."
            ),
            "levels": [
                {
                    "points": 20,
                    "description": (
                        "SEO är kärnan. Rank tracking, keyword research, on-page SEO, "
                        "länkbygge är huvudämnena. Inget tvivel."
                    ),
                },
                {
                    "points": 15,
                    "description": (
                        "SEO är en tydlig och återkommande del, men inte det enda fokuset. "
                        "Digital marketing-professional där SEO väger tungt."
                    ),
                },
                {
                    "points": 10,
                    "description": (
                        "SEO förekommer regelbundet men sidan vid sida med orelaterade ämnen "
                        "som e-handel, social media eller entrepreneurship."
                    ),
                },
                {
                    "points": 5,
                    "description": "SEO nämns sporadiskt. Inte ett fokusområde.",
                },
                {
                    "points": 0,
                    "description": (
                        "SEO saknas i princip helt, även om personen är inom marketing."
                    ),
                },
            ],
            "observable_signals": [
                "Ämnen i senaste 10–20 inläggen/videorna",
                "Profilbeskrivning",
                "Tjänstebeskrivning",
                "Kategoritaggar",
            ],
        },
        {
            "id": "purchase_influence",
            "name": "Köpinflytande",
            "emoji": "🛒",
            "max_points": 15,
            "rule": (
                "EVIDENCE REQUIRED — poängnivå MÅSTE stödjas av observerbar evidence. "
                "Yrkesroll/jobbtitel ensam räcker ALDRIG för 8/15 eller högre. "
                "Skilj tydligt: (a) ingen observerbar evidence → 5, "
                "(b) dokumenterad kundverksamhet men inga observerade tool-recs → 8, "
                "(c) observerad content/educator tool-evidence → 10, "
                "(d) tydlig observerad tool-rec för kunder/audience → 13, "
                "(e) stark och återkommande tool implementation + purchase influence → 15."
            ),
            "levels": [
                {
                    "points": 15,
                    "description": (
                        "Stark och återkommande observerbar evidence på aktiv tool "
                        "recommendation/implementation för kunder/audience, samt tydligt "
                        "purchase influence. T.ex. dedikerade verktygssidor, affiliate-program "
                        "för SEO-verktyg, regelbundna verktygsdemos för klienter."
                    ),
                },
                {
                    "points": 13,
                    "description": (
                        "Tydlig observerbar evidence att kandidaten rekommenderar eller väljer "
                        "SEO-verktyg för kunder eller audience. T.ex. inlägg/artiklar med "
                        "specifika verktygsrekommendationer, kursmoduler om verktygsval, "
                        "verifierade affiliate-länkar till SEO-verktyg."
                    ),
                },
                {
                    "points": 10,
                    "description": (
                        "Observerbar tool/content-evidence på educator eller content-creator-nivå. "
                        "T.ex. ett eller flera inlägg/videor med tool comparisons, "
                        "kursmaterial som inkluderar specifika verktyg, podcast-avsnitt om verktyg."
                    ),
                },
                {
                    "points": 8,
                    "description": (
                        "Stark professionell indikation på verktygsinflytande, men ingen direkt "
                        "observerad tool-recommendation. Kräver dokumenterad professionell "
                        "kund-/projektverksamhet som stöd (t.ex. etablerad byrå med ≥5 anställda, "
                        "verifierad kundbas) — jobbtitel ENSAM räcker INTE."
                    ),
                },
                {
                    "points": 5,
                    "description": (
                        "Ingen observerbar evidence på verktygsinflytande eller -rekommendation. "
                        "Markera insufficient_evidence: true."
                    ),
                },
            ],
            "observable_signals": [
                "Nämner specifika SEO-verktyg i inlägg, artiklar eller kursmaterial?",
                "Finns verifierbara affiliate-länkar till SEO-verktyg?",
                "Dokumenterad byrå-/konsultverksamhet med ≥5 anställda (stödjer nivå 8)?",
                "Är kandidatens aktiva kundbas explicit omnämnd?",
                "Klientportfölj, case studies eller testimonials synliga?",
            ],
        },
        {
            "id": "reach_quality",
            "name": "Räckvidd & audience-kvalitet",
            "emoji": "📣",
            "max_points": 10,
            "rule": (
                "VIKTIG REGEL: relevans väger tyngre än absoluta siffror. "
                "2 500 engagerade SEO-professionella kan slå 100 000 generella "
                "entreprenörsföljare."
            ),
            "levels": [
                {
                    "points": 10,
                    "description": (
                        "Stark räckvidd OCH hög audience-kvalitet. Engagerat, professionellt, "
                        "relevant. Kommentarer/interaktioner visar att följarna är inom SEO/marketing."
                    ),
                },
                {
                    "points": 7,
                    "description": (
                        "Bra räckvidd eller hög kvalitet, men inte båda. T.ex. liten men extremt "
                        "engagerad och relevant publik, eller stor publik med tydliga SEO-professionella."
                    ),
                },
                {
                    "points": 4,
                    "description": (
                        "Måttlig räckvidd och/eller tveksam audience-kvalitet. Svårt att bedöma "
                        "om publiken är köpstark."
                    ),
                },
                {
                    "points": 1,
                    "description": "Liten räckvidd och/eller låg audience-kvalitet. Få signaler på relevanta följare.",
                },
                {
                    "points": 0,
                    "description": "Ingen mätbar räckvidd eller uppenbar låg-kvalitetspublik (köpta följare, generiskt innehåll).",
                },
            ],
            "observable_signals": [
                "Följarantal",
                "Engagemangsgrad",
                "Kommentarskvalitet",
                "LinkedIn-titlar hos följare om synligt",
            ],
        },
        {
            "id": "customer_volume_potential",
            "name": "Potentiell kundvolym",
            "emoji": "💰",
            "max_points": 10,
            "rule": (
                "VIKTIG REGEL: spekulera INTE. Om konkret underlag saknas → markera "
                "insufficient_evidence: true och sätt max 4/10. Extrapolera ALDRIG från "
                "följarsiffror ensamt. "
                "AGENCY_FLOOR: Om kandidaten är en SEO-byrå eller SEO-konsult med "
                "dokumenterade anställda (≥5 st) ELLER med explicit nämnd aktiv kundbas "
                "→ sätt minimum 4/10 oavsett avsaknad av publicerade kundantal. "
                "Anledning: en byrå med 5+ anställda har rimligtvis betalande klienter, "
                "vilket är svagt men inte noll evidence."
            ),
            "levels": [
                {
                    "points": 10,
                    "description": (
                        "Starkt underlag finns. Byrå med känd kundbas, utbildare med dokumenterat "
                        "antal kurs-/community-deltagare. Kan realistiskt generera 5+ betalande kunder."
                    ),
                },
                {
                    "points": 7,
                    "description": (
                        "Gott underlag. Konsult med tydlig aktiv kundbas eller creator med relevant "
                        "och engagerad publik. Kan realistiskt generera 2–4 kunder."
                    ),
                },
                {
                    "points": 4,
                    "description": (
                        "Begränsat underlag. Potential finns men lite konkret att bedöma mot. "
                        "Troligen 1–2 kunder om affiliaten är aktiv."
                    ),
                },
                {
                    "points": 1,
                    "description": "Svagt underlag eller tydligt liten relevant räckvidd. Enstaka kund i bästa fall.",
                },
                {
                    "points": 0,
                    "description": "Inget underlag alls, eller uppenbart ingen realistisk kundvolym.",
                },
            ],
            "observable_signals": [
                "Antal kunder/elever om uppgett",
                "Community-storlek",
                "Byrå-storlek",
                "LinkedIn-anställda (≥5 triggerar AGENCY_FLOOR: minimum 4/10)",
                "Explicit nämnd aktiv kundbas (t.ex. '30+ klienter', 'kursgrupp 200 elever')",
                "Om ingen av dessa är synliga → insufficient_evidence: true, max 4/10",
            ],
        },
        {
            "id": "brazil_fit",
            "name": "Brasilien-fit",
            "emoji": "🇧🇷",
            "max_points": 5,
            "rule": "Bedöm om publiken faktiskt är brasiliansk/lusofon.",
            "levels": [
                {
                    "points": 5,
                    "description": (
                        "Tydligt brasiliansk publik, innehåll på portugisiska, brasilianska "
                        "referenser och marknadskontext."
                    ),
                },
                {
                    "points": 3,
                    "description": (
                        "Övervägande brasiliansk/lusofon publik men med visst internationellt inslag, "
                        "eller portugisiskt innehåll utan tydliga brasilianska signaler."
                    ),
                },
                {
                    "points": 1,
                    "description": "LATAM-relevant men inte specifikt Brasilien. Spanska eller blandat.",
                },
                {
                    "points": 0,
                    "description": "Inte brasiliansk/lusofon publik.",
                },
            ],
            "observable_signals": [
                "Språk i innehåll",
                "Geo-taggar",
                "Omnämnande av brasilianska städer/kunder/marknaden",
                "Profilplats",
            ],
        },
        {
            "id": "affiliate_fit",
            "name": "Affiliate-fit",
            "emoji": "🤝",
            "max_points": 5,
            "rule": "Bedöm sannolikhet att personen faktiskt vill rekommendera och arbeta med oss.",
            "levels": [
                {
                    "points": 5,
                    "description": (
                        "Tydliga signaler: rekommenderar redan verktyg, har affiliate-program, "
                        "eller bygger aktivt partnerskap. Öppen för samarbeten."
                    ),
                },
                {
                    "points": 3,
                    "description": (
                        "Neutral — ingen tydlig signal åt något håll. Professionell och seriös "
                        "men inget direkt indikerar affiliate-erfarenhet."
                    ),
                },
                {
                    "points": 1,
                    "description": (
                        "Svaga signaler. Verkar tveksam till kommersiella samarbeten, väldigt "
                        "fokuserad på 'oberoende' eller har uttalat sig negativt om affiliates."
                    ),
                },
                {
                    "points": 0,
                    "description": (
                        "Tydlig intressekonflikt (konkurrent, exklusivt partnerskap med rival) "
                        "eller uppenbart olämplig."
                    ),
                },
            ],
            "observable_signals": [
                "Befintliga affiliate-länkar",
                "Sponsrade inlägg",
                "'Partners'-sida",
                "Bio-beskrivning",
                "Samarbetshistorik",
            ],
        },
        {
            "id": "content_traffic_potential",
            "name": "Content/traffic potential",
            "emoji": "📈",
            "max_points": 5,
            "rule": "Evergreen-innehåll (blogg, YouTube) > flyktigt (stories, sociala medier).",
            "levels": [
                {
                    "points": 5,
                    "description": (
                        "Evergreen SEO-innehåll, aktiv YouTube-kanal med verktygsvideor, "
                        "newsletter med hög öppningsfrekvens. Genererar leads passivt över tid."
                    ),
                },
                {
                    "points": 3,
                    "description": (
                        "Aktivt innehållsskapande men mer flyktigt (sociala medier, stories). "
                        "Bra nu men inte långsiktigt passivt."
                    ),
                },
                {
                    "points": 1,
                    "description": "Sporadiskt innehåll eller kanal som tappat momentum.",
                },
                {
                    "points": 0,
                    "description": "Inget innehåll av substans eller inaktiv kanal.",
                },
            ],
            "observable_signals": [
                "Publiceringsfrekvens",
                "Innehållstyp (blogg/video vs stories)",
                "YouTube-visningar per video",
                "Ahrefs/SEMrush-data om tillgängligt",
            ],
        },
    ],
    "knockout_filters": [
        "Ingen relevant brasiliansk/lusofon publik",
        "Ingen verklig SEO-/marketingrelevans",
        "Spam/low-quality audience",
        "Konkurrent eller uppenbar intressekonflikt",
    ],
    "classification": [
        {"min": 90, "max": 100, "grade": "A+", "label": "Kontakta direkt — personlig outreach"},
        {"min": 80, "max": 89,  "grade": "A",  "label": "Mycket intressant — hög prioritet"},
        {"min": 70, "max": 79,  "grade": "B",  "label": "Bra kandidat — kontakta efter A-listan"},
        {"min": 60, "max": 69,  "grade": "C",  "label": "Databasen — ingen prioritet initialt"},
        {"min": 0,  "max": 59,  "grade": "Skip", "label": "Prioritera inte"},
    ],
}


def get_classification(total_score: int) -> dict:
    """Return grade + label for a given total score."""
    for cls in SCORE_MODEL["classification"]:
        if cls["min"] <= total_score <= cls["max"]:
            return cls
    return {"grade": "Skip", "label": "Prioritera inte"}
