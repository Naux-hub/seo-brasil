"""
seed_cache_mx.py
================
Pre-popula el keyword_cache de Supabase con ~200 términos de SEO en español
para el mercado mexicano (location_code=2484).

Objetivo: asegurarse de que los primeros usuarios de SEO México vean
resultados inmediatos al buscar términos comunes, sin esperar a que el
caché se llene orgánicamente.

Uso:
    python seed_cache_mx.py

Requiere variables de entorno (o .env en la raíz del proyecto):
    SUPABASE_URL
    SUPABASE_KEY
    DATAFORSEO_LOGIN
    DATAFORSEO_PASSWORD

El script usa keyword_cache.get_keyword_data() directamente, que ya
maneja la lógica de caché + batch + upsert. Cada keyword costará ~$0.009
si no está ya en caché.

Estimación de costo:
    ~200 términos / 10 por batch = 20 batches × $0.09 = ~$1.80 USD total.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Cargar .env desde la raíz del proyecto
load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL        = os.environ["SUPABASE_URL"]
SUPABASE_KEY        = os.environ["SUPABASE_KEY"]
DATAFORSEO_LOGIN    = os.environ["DATAFORSEO_LOGIN"]
DATAFORSEO_PASSWORD = os.environ["DATAFORSEO_PASSWORD"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Necesitamos MARKET=mx para que keyword_cache use location_code=2484
os.environ["MARKET"] = "mx"
from keyword_cache import get_keyword_data   # noqa: E402  (importar después de setear env)

# ---------------------------------------------------------------------------
# Seed keywords — términos SEO de alto volumen en México
# ---------------------------------------------------------------------------

SEED_KEYWORDS = [
    # Fundamentos de SEO
    "seo",
    "posicionamiento en google",
    "optimización seo",
    "seo para principiantes",
    "seo local",
    "seo on page",
    "seo off page",
    "seo técnico",
    "auditoria seo",
    "estrategia seo",
    "mejores prácticas seo",
    "seo para ecommerce",
    "seo para wordpress",
    "seo gratis",
    "herramientas seo gratis",

    # Investigación de palabras clave
    "palabras clave",
    "investigación de palabras clave",
    "volumen de búsqueda",
    "keyword research",
    "palabras clave long tail",
    "palabras clave de cola larga",
    "intención de búsqueda",
    "densidad de palabras clave",
    "palabras clave negativas",
    "palabras clave de alto tráfico",

    # Contenido
    "marketing de contenidos",
    "redacción seo",
    "blog seo",
    "contenido optimizado",
    "meta descripción",
    "título seo",
    "encabezados h1 h2",
    "texto alternativo imágenes",
    "contenido evergreen",
    "contenido duplicado",

    # Link building
    "link building",
    "backlinks",
    "enlaces entrantes",
    "autoridad de dominio",
    "perfil de enlaces",
    "guest posting",
    "nofollow dofollow",
    "anchor text",
    "dominios de referencia",
    "construcción de enlaces",

    # SEO técnico
    "velocidad del sitio web",
    "core web vitals",
    "sitemap xml",
    "robots txt",
    "canonical url",
    "redirección 301",
    "https ssl",
    "mobile first indexing",
    "diseño responsive",
    "arquitectura web",
    "crawl budget",
    "errores 404",
    "paginación seo",
    "datos estructurados",
    "schema markup",

    # Herramientas
    "google search console",
    "google analytics 4",
    "semrush",
    "ahrefs",
    "moz",
    "ubersuggest",
    "screaming frog",
    "google keyword planner",
    "google trends",
    "yoast seo",

    # Local SEO
    "seo local mexico",
    "google my business",
    "perfil de empresa google",
    "reseñas google",
    "citas locales",
    "nap consistencia",
    "búsquedas locales",
    "aparecer en google maps",
    "posicionamiento local",
    "seo para restaurantes",
    "seo para abogados",
    "seo para médicos",
    "seo para hoteles",
    "seo para inmobiliarias",

    # E-commerce
    "seo para tienda en línea",
    "tienda online mexico",
    "woocommerce seo",
    "shopify seo",
    "descripción de producto seo",
    "categoría de producto seo",
    "ficha de producto",
    "carrito de compras",
    "checkout optimizado",
    "seo para amazon",

    # Marketing digital
    "marketing digital mexico",
    "agencia de marketing digital",
    "agencia seo mexico",
    "consultor seo",
    "especialista seo",
    "curso seo",
    "aprender seo",
    "certificación google",
    "inbound marketing",
    "funnel de ventas",
    "embudo de conversión",
    "tasa de conversión",
    "cro",
    "landing page optimizada",
    "a/b testing",

    # Redes sociales y SEO
    "redes sociales y seo",
    "señales sociales seo",
    "youtube seo",
    "video seo",
    "instagram seo",
    "tiktok seo",

    # Análisis y métricas
    "tasa de rebote",
    "tiempo en página",
    "páginas por sesión",
    "sesiones orgánicas",
    "clics orgánicos",
    "impresiones google",
    "ctr seo",
    "posición media google",
    "tráfico orgánico",
    "palabras clave posicionadas",
    "ranking de palabras clave",
    "seguimiento de posiciones",
    "rastreo de keywords",

    # Nichos populares en México
    "seo para blogs",
    "seo para noticias",
    "seo para podcasts",
    "seo para freelancers",
    "seo para pymes",
    "seo para startups",
    "seo para agencias",
    "seo para consultores",
    "seo para coaches",
    "seo para dentistas",

    # Tendencias
    "seo inteligencia artificial",
    "seo con chatgpt",
    "search generative experience",
    "sge google",
    "voice search seo",
    "búsqueda por voz",
    "featured snippets",
    "fragmentos destacados",
    "rich results",
    "e-e-a-t google",
    "experiencia autoridad confianza",
    "helpful content update",
    "google algorithm updates",
    "core update google",
    "penalización google",

    # Términos de negocio
    "como aparecer en google",
    "salir primero en google",
    "primera página de google",
    "subir posiciones google",
    "mejorar posicionamiento web",
    "aumentar tráfico web",
    "conseguir visitas web",
    "más clientes por internet",
    "vender más por internet",
    "presencia digital",
    "visibilidad online",
    "reputación online",

    # Términos técnicos adicionales
    "indexación google",
    "rastreabilidad",
    "crawling e indexación",
    "javascript seo",
    "seo para react",
    "seo para apps",
    "app store optimization",
    "aso",
    "ppc vs seo",
    "seo vs sem",
    "google ads vs seo",
    "tráfico pago vs orgánico",
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  SEO México — Keyword Cache Seed")
    print(f"  Total de términos: {len(SEED_KEYWORDS)}")
    print(f"  Mercado: MX (location_code=2484, language=es)")
    print("=" * 60)
    print()

    # Verificar que no hay duplicados en la lista
    seen = set()
    unique_keywords = []
    for kw in SEED_KEYWORDS:
        kw_norm = kw.strip().lower()
        if kw_norm not in seen:
            seen.add(kw_norm)
            unique_keywords.append(kw.strip())
    print(f"Únicos después de deduplicar: {len(unique_keywords)}")

    if "--dry-run" in sys.argv:
        print("\n[DRY-RUN] Se procesarían los siguientes términos:")
        for i, kw in enumerate(unique_keywords, 1):
            print(f"  {i:3}. {kw}")
        print("\nEjecuta sin --dry-run para hacer las peticiones reales.")
        return

    print("\nEjecutando get_keyword_data() para todos los términos...")
    print("(Los términos ya en caché no generan costo adicional)\n")

    try:
        results = get_keyword_data(unique_keywords, supabase, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD)
        cached  = sum(1 for v in results.values() if v is not None)
        print(f"\n✅ Completado: {cached}/{len(unique_keywords)} términos en caché.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
