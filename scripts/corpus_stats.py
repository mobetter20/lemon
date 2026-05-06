"""Validate the corpus against Phase 1 gates.

Hard gates:
  - records >= 2,000 (degraded floor) or >= 5,000 (full target)
  - >= 6 months date range
  - >= 30% per model family (claude, openai), counting "both" as half each

Soft warnings:
  - < 3 release events covered (warn until releases.json populated)
  - degraded mode (records between 2k and 5k)

Exit codes:
  0  all hard gates pass (warnings allowed)
  1  one or more hard gates failed
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_corpus(corpus_dir: Path):
    for shard in sorted(corpus_dir.rglob("*.ndjson")):
        with open(shard) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"  bad line in {shard}: {e}", file=sys.stderr)


def main(corpus_dir: Path = ROOT / "corpus") -> int:
    total = 0
    by_source: Counter = Counter()
    by_month: Counter = Counter()
    by_model: Counter = Counter()
    release_events: set[str] = set()

    for rec in load_corpus(corpus_dir):
        total += 1
        by_source[rec.get("source", "unknown")] += 1
        date = rec.get("date") or ""
        if len(date) >= 7:
            by_month[date[:7]] += 1
        by_model[rec.get("model_mentioned", "unknown")] += 1
        rel = rec.get("mentions_release_event")
        if rel:
            release_events.add(rel)

    print(f"Total records:       {total}")
    print(f"By source:           {dict(by_source)}")
    print(f"Months covered:      {len(by_month)}")
    if by_month:
        sample_months = sorted(by_month.keys())
        print(f"  range:             {sample_months[0]} .. {sample_months[-1]}")
    print(f"By model_mentioned:  {dict(by_model)}")
    print(f"Release events seen: {len(release_events)}")
    if release_events:
        print(f"  ids:               {sorted(release_events)}")

    failures = []
    full_min, degraded_min = 5000, 2000

    if total < degraded_min:
        failures.append(f"records {total} < {degraded_min} (degraded floor)")
    elif total < full_min:
        print(f"\nWARN: degraded mode ({total} records, full target was {full_min})")

    if len(by_month) < 6:
        failures.append(f"months covered {len(by_month)} < 6")

    if total > 0:
        both = by_model.get("both", 0)
        claude_share = (by_model.get("claude", 0) + both / 2) / total
        openai_share = (by_model.get("openai", 0) + both / 2) / total
        if claude_share < 0.30:
            failures.append(f"claude share {claude_share:.0%} < 30%")
        if openai_share < 0.30:
            failures.append(f"openai share {openai_share:.0%} < 30%")
        skew = max(claude_share, openai_share) / max(min(claude_share, openai_share), 1e-9)
        if skew > (0.7 / 0.3):
            failures.append(
                f"skew worse than 70/30 (claude={claude_share:.0%}, openai={openai_share:.0%})"
            )

    if len(release_events) < 3:
        print(
            f"\nWARN: only {len(release_events)} release events covered. "
            f"Populate config/releases.json before Phase 5."
        )

    if failures:
        print("\nFAIL — hard gates:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll hard gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
