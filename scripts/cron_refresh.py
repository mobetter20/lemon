"""Cron refresh: incremental scrape for the Phase 4 cron.

Runs HN Algolia + Reddit historical (arctic_shift) for the last ~30 days.
Skips reddit_recent entirely — option C from the 2026-05-07 design: GH
Actions runner IPs are 403'd by Reddit's unauth JSON endpoint, and PRAW
is blocked account-side. We accept arctic_shift's 24-48h lag in exchange
for zero recurring cost.

Self-healing: if the corpus/ directory is empty (cache miss or first run),
falls back to a 12-month full backfill. Otherwise runs an incremental
30-day window (covers cron interval + arctic_shift indexing lag + buffer).
The dedup index makes overlapping windows cheap.

Exit codes:
  0 — refresh completed (records may be 0 if no new posts; that's not failure)
  1 — both scrapers failed entirely (real outage)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.common import DedupIndex  # noqa: E402
from scrapers.hn import scrape_hn  # noqa: E402
from scrapers.reddit_historical import scrape_reddit_historical  # noqa: E402


def _corpus_has_data(corpus_dir: Path) -> bool:
    return any(corpus_dir.rglob("*.ndjson"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus-dir", type=Path, default=ROOT / "corpus")
    p.add_argument("--config-dir", type=Path, default=ROOT / "config")
    p.add_argument(
        "--months-back",
        type=int,
        default=1,
        help="Window for incremental run. Defaults to 1 (last ~30 days).",
    )
    p.add_argument(
        "--backfill-months",
        type=int,
        default=12,
        help="Fallback window if corpus is empty (cache miss).",
    )
    args = p.parse_args()

    args.corpus_dir.mkdir(parents=True, exist_ok=True)
    dedup = DedupIndex(args.corpus_dir / ".dedup.db")

    if _corpus_has_data(args.corpus_dir):
        months = args.months_back
        mode = "incremental"
    else:
        months = args.backfill_months
        mode = "backfill"
    print(f"[cron_refresh] mode={mode} months_back={months}", flush=True)

    hn_records = 0
    hn_failed = False
    try:
        hn_records = scrape_hn(args.corpus_dir, args.config_dir, months, dedup)
    except Exception as e:
        print(f"[cron_refresh] HN scrape FAILED: {e}", flush=True)
        hn_failed = True

    reddit_records = 0
    reddit_failed = False
    try:
        reddit_records = scrape_reddit_historical(
            args.corpus_dir,
            args.config_dir,
            months,
            dedup,
            use_arctic_shift=True,
        )
    except Exception as e:
        print(f"[cron_refresh] arctic_shift scrape FAILED: {e}", flush=True)
        reddit_failed = True

    dedup.close()

    print(
        f"[cron_refresh] done. hn_new={hn_records} reddit_new={reddit_records}",
        flush=True,
    )

    if hn_failed and reddit_failed:
        print("[cron_refresh] BOTH scrapers failed. Exit 1.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
