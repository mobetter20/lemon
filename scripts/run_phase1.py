"""Phase 1 orchestrator — run all scrapers, write to corpus/, then summarize.

Examples:
  # Smoke test (2 months back, HN only)
  python scripts/run_phase1.py --months-back 2 --skip-reddit-historical --skip-reddit-recent

  # Full run with arctic_shift fallback
  python scripts/run_phase1.py --use-arctic-shift
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
from scrapers.reddit_recent import scrape_reddit_recent  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--months-back", type=int, default=12)
    parser.add_argument("--skip-hn", action="store_true")
    parser.add_argument("--skip-reddit-historical", action="store_true")
    parser.add_argument("--skip-reddit-recent", action="store_true")
    parser.add_argument(
        "--use-arctic-shift",
        action="store_true",
        help="Use arctic_shift instead of pullpush for Reddit historical",
    )
    parser.add_argument(
        "--limit-hn-stories",
        type=int,
        default=None,
        help="Cap HN stories per query/window (smoke testing)",
    )
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "corpus")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    args = parser.parse_args()

    args.corpus_dir.mkdir(parents=True, exist_ok=True)
    dedup = DedupIndex(args.corpus_dir / ".dedup.db")

    total = 0
    if not args.skip_hn:
        total += scrape_hn(
            args.corpus_dir,
            args.config_dir,
            args.months_back,
            dedup,
            limit_stories_per_window=args.limit_hn_stories,
        )
    if not args.skip_reddit_historical:
        total += scrape_reddit_historical(
            args.corpus_dir,
            args.config_dir,
            args.months_back,
            dedup,
            use_arctic_shift=args.use_arctic_shift,
        )
    if not args.skip_reddit_recent:
        total += scrape_reddit_recent(args.corpus_dir, args.config_dir, dedup)

    dedup.close()
    print(f"\nPhase 1 complete. Total records written: {total}")
    print("Run scripts/corpus_stats.py to validate gates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
