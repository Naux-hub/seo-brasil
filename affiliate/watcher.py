"""
affiliate/watcher.py
====================
Prospect file watcher for SEO Brasil affiliate scoring.

Monitors prospects/br/ for new JSON files and automatically runs scorer.py
on any prospect that does not yet have a report in reports/br/.

No external dependencies — uses only Python stdlib (polling-based).

Usage:
    # Watch continuously (run once, stays alive):
    python watcher.py

    # Score all unscored prospects once, then exit:
    python watcher.py --once

    # Watch a different market (future use):
    python watcher.py --market mx

Options:
    --once      Score all pending prospects and exit. Good for batch runs.
    --market    Market to watch (default: br)
    --interval  Poll interval in seconds (default: 10)
    --dry-run   Show which files would be scored, but don't run scorer.

How it detects "already scored":
    A prospect file prospects/br/NAME.json is considered scored if reports/br/
    contains at least one file whose name starts with the slug derived from
    the candidate's "name" field inside the JSON (same logic as scorer.py).
    Example: {"name": "Amanda Noronha Araujo"} → slug = amanda_noronha_araujo
             Reports starting with amanda_noronha_araujo_* → already scored.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

AFFILIATE_DIR = Path(__file__).parent
SCORER = AFFILIATE_DIR / "scorer.py"


def get_prospects_dir(market: str) -> Path:
    return AFFILIATE_DIR / "prospects" / market


def get_reports_dir(market: str) -> Path:
    return AFFILIATE_DIR / "reports" / market


# ---------------------------------------------------------------------------
# CORE LOGIC
# ---------------------------------------------------------------------------

def slug_from_json(path: Path) -> str | None:
    """Read the 'name' field from a prospect JSON and return its slug.
    Returns None if the file can't be read or has no name field.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("name", "").strip()
        if not name:
            return None
        return name.lower().replace(" ", "_").replace("/", "_")
    except Exception:
        return None


def already_scored(slug: str, reports_dir: Path) -> bool:
    """Return True if reports_dir contains at least one file starting with slug_."""
    if not reports_dir.exists():
        return False
    pattern = f"{slug}_*.json"
    return any(reports_dir.glob(pattern))


def find_pending(market: str) -> list[Path]:
    """Return prospect files that have not yet been scored."""
    prospects_dir = get_prospects_dir(market)
    reports_dir = get_reports_dir(market)

    if not prospects_dir.exists():
        return []

    pending = []
    for f in sorted(prospects_dir.glob("*.json")):
        if f.stem == "template":
            continue
        slug = slug_from_json(f)
        if slug is None:
            _log(f"⚠️  Kunde inte läsa 'name' från {f.name} — hoppar över.")
            continue
        if not already_scored(slug, reports_dir):
            pending.append(f)

    return pending


def run_scorer(prospect_path: Path) -> bool:
    """Run scorer.py on a single prospect file. Returns True on success."""
    cmd = [sys.executable, str(SCORER), str(prospect_path)]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(AFFILIATE_DIR),
            capture_output=False,   # let output stream to terminal
            text=True,
        )
        return result.returncode == 0
    except Exception as e:
        _log(f"  FEL vid körning av scorer: {e}")
        return False


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# MODES
# ---------------------------------------------------------------------------

def run_once(market: str, dry_run: bool) -> int:
    """Score all pending prospects and return count scored."""
    pending = find_pending(market)

    if not pending:
        _log(f"✅  Inga väntande prospects i prospects/{market}/")
        return 0

    _log(f"🔍  Hittade {len(pending)} oscorade prospect(s) i prospects/{market}/:")
    for f in pending:
        _log(f"    · {f.name}")

    if dry_run:
        _log("(dry-run — kör ingenting)")
        return 0

    scored = 0
    for f in pending:
        _log(f"\n▶  Kör scorer på {f.name}...")
        ok = run_scorer(f)
        if ok:
            scored += 1
        else:
            _log(f"  ⚠️  Scorer returnerade fel för {f.name}")

    _log(f"\n✅  Klar — {scored}/{len(pending)} prospects scorade.")
    return scored


def run_watch(market: str, interval: int, dry_run: bool) -> None:
    """Watch continuously and score new prospects as they appear."""
    prospects_dir = get_prospects_dir(market)
    _log(f"👁️  Bevakar {prospects_dir}/ (kontrollerar var {interval}s)")
    _log("   Ctrl+C för att avsluta.\n")

    seen_scored: set[str] = set()

    # Populate seen_scored with already-scored prospects at startup
    # so we don't re-score old ones when the watcher starts.
    for f in sorted(prospects_dir.glob("*.json")) if prospects_dir.exists() else []:
        if f.stem == "template":
            continue
        slug = slug_from_json(f)
        if slug and already_scored(slug, get_reports_dir(market)):
            seen_scored.add(f.stem)

    _log(f"   {len(seen_scored)} prospects redan scorade vid uppstart — hoppar över dem.")
    _log("")

    try:
        while True:
            pending = find_pending(market)
            # Filter out any we've already handled this session
            new_pending = [f for f in pending if f.stem not in seen_scored]

            for f in new_pending:
                _log(f"🆕  Ny prospect: {f.name}")
                if dry_run:
                    _log("   (dry-run — kör ingenting)")
                else:
                    _log(f"▶  Kör scorer...")
                    ok = run_scorer(f)
                    if ok:
                        _log(f"✅  {f.name} → rapport sparad i reports/{market}/")
                    else:
                        _log(f"⚠️  Scorer returnerade fel för {f.name}")
                seen_scored.add(f.stem)

            time.sleep(interval)

    except KeyboardInterrupt:
        _log("\n👋  Watcher avslutad.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SEO Brasil — Affiliate Prospect Watcher"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Score alla oscorade prospects en gång och avsluta",
    )
    parser.add_argument(
        "--market",
        default="br",
        help="Marknad att bevaka (default: br)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Pollingsintervall i sekunder (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Visa vilka filer som skulle scoreas, men kör inget",
    )
    args = parser.parse_args()

    if not SCORER.exists():
        print(f"Fel: scorer.py hittades inte på {SCORER}", file=sys.stderr)
        sys.exit(1)

    print()
    print("=" * 50)
    print("  SEO Brasil — Affiliate Watcher")
    print(f"  Marknad: {args.market.upper()}")
    if args.once:
        print("  Läge: --once (kör och avslutar)")
    else:
        print(f"  Läge: kontinuerlig bevakning (var {args.interval}s)")
    if args.dry_run:
        print("  ⚠️  DRY-RUN — ingenting körs")
    print("=" * 50)
    print()

    if args.once:
        run_once(args.market, args.dry_run)
    else:
        run_watch(args.market, args.interval, args.dry_run)


if __name__ == "__main__":
    main()
