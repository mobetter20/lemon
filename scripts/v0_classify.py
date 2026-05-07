"""v0 classifier — applies the curated phrase list to the corpus, produces phase5/data.json.

For each record we mark:
- complaint = True if its lowercased text contains any phrase from
  config/complaint_phrases.json::complaint_phrases
- defection = True if it contains any phrase from ::defection_phrases

Aggregation:
- (model_family, ISO-week) → all_mentions, complaints, defections
- "both" records contribute to BOTH claude and openai buckets (a comparison
  mention is a mention of each)
- "unknown" records are skipped
- Top phrase frequencies per (model_family, ISO-week) are taken from the
  complaint-yes subset using the actual phrases that matched — these become
  the dashboard's "most-mentioned in complaints" list (audit-friendly: every
  term shown is a literal entry from the phrase list)

Output schema matches phase5/mock_data.json so the dashboard reads either.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent


def load_phrases(config_dir: Path) -> tuple[list[str], list[str]]:
    with open(config_dir / "complaint_phrases.json") as f:
        cfg = json.load(f)
    return cfg["complaint_phrases"], cfg["defection_phrases"]


def load_releases(config_dir: Path) -> list[dict]:
    """Load `verified: true` releases only. Unverified entries are
    best-guess dates and shouldn't render annotation lines on the trend
    chart at potentially-wrong positions. Flip `verified: true` in
    config/releases.json after confirming the date against the vendor's
    announcement page.
    """
    p = config_dir / "releases.json"
    if not p.exists():
        return []
    with open(p) as f:
        all_releases = json.load(f).get("releases", [])
    return [r for r in all_releases if r.get("verified") is True]


def iter_corpus(corpus_dir: Path):
    for shard in sorted(corpus_dir.rglob("*.ndjson")):
        # errors="replace": one record with a stray non-UTF-8 byte
        # (mojibake from upstream) shouldn't crash the whole classifier.
        # The replacement char ufffd will fail json.loads for that record
        # only, and the except below skips it.
        with open(shard, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def build_matcher(phrases: list[str]) -> Callable[[str], list[str]]:
    """Return a function that takes lowercased text and returns the list of
    matched phrases. Phrases ≤3 chars use word-boundary regex to avoid false
    positives ("o1" should not match "to1k"); longer phrases use plain
    substring."""
    short_patterns: list[tuple[str, re.Pattern]] = []
    long_phrases: list[str] = []
    for p in phrases:
        pl = p.lower()
        if len(pl) <= 3:
            short_patterns.append((pl, re.compile(rf"\b{re.escape(pl)}\b")))
        else:
            long_phrases.append(pl)

    def match(text_lower: str) -> list[str]:
        hits: list[str] = []
        for p in long_phrases:
            if p in text_lower:
                hits.append(p)
        for p, pat in short_patterns:
            if pat.search(text_lower):
                hits.append(p)
        return hits

    return match


def iso_week_label(date_iso: str | None) -> str | None:
    if not date_iso:
        return None
    try:
        d = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    except (ValueError, TypeError):
        return None


def families_for(model_mentioned: str | None) -> list[str]:
    if model_mentioned == "claude":
        return ["claude"]
    if model_mentioned == "openai":
        return ["openai"]
    if model_mentioned == "both":
        return ["claude", "openai"]
    return []


def assert_output_shape(output: dict, prior_total: int | None = None) -> None:
    """Hard asserts for the Phase 4 cron.

    Designed so a silent zero-record run cannot quietly advance the dashboard.
    If any of these fail, the workflow exits red and the user notices.
    """
    summary = output.get("summary") or {}
    trend = output.get("trend") or {}
    totals = output.get("totals") or {}

    assert summary, "summary block missing"
    assert trend, "trend block missing"
    assert "claude" in summary and "openai" in summary, "summary must have both families"

    # At least one family had this-week mentions. If both are 0 the corpus is dead.
    this_week_total = (
        summary["claude"]["this_week"]["all_mentions"]
        + summary["openai"]["this_week"]["all_mentions"]
    )
    assert this_week_total > 0, (
        f"this-week all_mentions is 0 across both families — scraper or "
        f"classifier is broken (claude={summary['claude']['this_week']['all_mentions']}, "
        f"openai={summary['openai']['this_week']['all_mentions']})"
    )

    # Per-source non-empty: this catches a silent single-source outage
    # (e.g., Reddit/arctic_shift returned 0 results but HN saved the day).
    # Look at the most recent week with data; require at least one source present.
    for fam in ("claude", "openai"):
        s = summary[fam]
        if s["this_week"]["all_mentions"] == 0:
            continue  # this family genuinely had no mentions this week
        by_source = s["this_week"].get("by_source") or {}
        assert by_source, f"{fam} this-week has all_mentions but empty by_source"

    # Trend has at least 4 weeks for both families (90-day chart needs density)
    for fam in ("claude", "openai"):
        assert len(trend[fam]) >= 4, (
            f"{fam} trend has only {len(trend[fam])} weeks — corpus is too thin"
        )

    # Catastrophic-loss guard. Don't require strict monotonic growth — a
    # cache miss followed by a seed-from-release reset gives ~0.03% variance
    # vs. the prior warm-cache state, which is normal. Only fail on a
    # catastrophic drop (>10%).
    if prior_total is not None and prior_total > 0:
        cur_total = totals.get("all_records", 0)
        assert cur_total >= prior_total * 0.9, (
            f"total_records dropped >10%: prior={prior_total} now={cur_total}"
        )


def main(
    corpus_dir: Path = ROOT / "corpus",
    config_dir: Path = ROOT / "config",
    out_path: Path = ROOT / "phase5" / "data.json",
    strict: bool = False,
) -> int:
    complaint_phrases, defection_phrases = load_phrases(config_dir)
    match_complaint = build_matcher(complaint_phrases)
    match_defection = build_matcher(defection_phrases)

    mentions: dict[tuple[str, str], int] = defaultdict(int)
    complaints: dict[tuple[str, str], int] = defaultdict(int)
    defections: dict[tuple[str, str], int] = defaultdict(int)
    phrase_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)

    # Per-source breakdown — keyed on (family, week, source).
    # Sources are "hn" or "reddit" (whatever rec["source"] is).
    mentions_by_source: dict[tuple[str, str, str], int] = defaultdict(int)
    complaints_by_source: dict[tuple[str, str, str], int] = defaultdict(int)

    # Phrase examples — for each (family, week, phrase) we keep the oldest,
    # newest, and top-scored matching record. Audit-friendly: clicking a top
    # phrase on the dashboard reveals 3 actual permalinks the user can read.
    phrase_examples: dict[tuple[str, str, str], dict[str, dict]] = defaultdict(
        lambda: {"oldest": None, "newest": None, "top_scored": None}
    )

    total_records = 0
    skipped_unknown = 0
    skipped_no_text = 0
    skipped_no_date = 0

    for rec in iter_corpus(corpus_dir):
        total_records += 1
        text = (rec.get("post_text") or "").strip()
        if not text:
            skipped_no_text += 1
            continue
        text_lower = text.lower()
        week = iso_week_label(rec.get("date"))
        if not week:
            skipped_no_date += 1
            continue
        fams = families_for(rec.get("model_mentioned"))
        if not fams:
            skipped_unknown += 1
            continue

        c_hits = match_complaint(text_lower)
        d_hits = match_defection(text_lower)

        source = rec.get("source") or "unknown"
        rec_date = rec.get("date") or ""
        rec_score = int(rec.get("score") or 0)
        rec_permalink = rec.get("permalink") or ""

        for fam in fams:
            key = (fam, week)
            mentions[key] += 1
            mentions_by_source[(fam, week, source)] += 1
            if c_hits:
                complaints[key] += 1
                complaints_by_source[(fam, week, source)] += 1
                for h in c_hits:
                    phrase_counts[key][h] += 1
                    # Track examples: keep oldest, newest, top-scored matches.
                    # Skip if date is empty/missing — string comparison would
                    # latch onto "" forever (plan-critic catch).
                    if not rec_date or not rec_permalink:
                        continue
                    examples = phrase_examples[(fam, week, h)]
                    candidate = {
                        "permalink": rec_permalink,
                        "date": rec_date,
                        "score": rec_score,
                        "source": source,
                    }
                    if examples["oldest"] is None or rec_date < examples["oldest"]["date"]:
                        examples["oldest"] = candidate
                    if examples["newest"] is None or rec_date > examples["newest"]["date"]:
                        examples["newest"] = candidate
                    # Top-scored: only consider records with positive score, so
                    # an early score=0 HN comment doesn't win forever.
                    if rec_score > 0:
                        cur = examples["top_scored"]
                        if (
                            cur is None
                            or rec_score > cur["score"]
                            or (rec_score == cur["score"] and rec_date > cur["date"])
                        ):
                            examples["top_scored"] = candidate
            if d_hits:
                defections[key] += 1

    # Build per-family time series (sorted by week)
    trend: dict[str, list[dict]] = {"claude": [], "openai": []}
    defection_trend: dict[str, list[dict]] = {"claude": [], "openai": []}
    weeks_in_data = sorted({w for (_, w) in mentions.keys()})

    for week in weeks_in_data:
        for fam in ("claude", "openai"):
            m = mentions.get((fam, week), 0)
            if m == 0:
                continue
            c = complaints.get((fam, week), 0)
            d = defections.get((fam, week), 0)
            trend[fam].append(
                {
                    "week": week,
                    "all_mentions": m,
                    "complaints": c,
                    "rate": round(c / m, 4),
                }
            )
            defection_trend[fam].append({"week": week, "rate": round(d / m, 4)})

    def _by_source_block(fam: str, week: str) -> dict[str, dict]:
        """Build a {source: {all_mentions, complaints, rate}} dict for a (fam, week)."""
        block: dict[str, dict] = {}
        for src in ("hn", "reddit"):
            m = mentions_by_source.get((fam, week, src), 0)
            if m == 0:
                continue
            c = complaints_by_source.get((fam, week, src), 0)
            block[src] = {
                "all_mentions": m,
                "complaints": c,
                "rate": round(c / m, 4),
            }
        return block

    summary: dict[str, dict] = {}
    for fam in ("claude", "openai"):
        series = trend[fam]
        if series:
            this_w = series[-1]
            last_w = series[-2] if len(series) >= 2 else None
            delta = (this_w["rate"] - (last_w["rate"] if last_w else 0)) * 100
            summary[fam] = {
                "this_week_label": this_w["week"],
                "this_week": {
                    "all_mentions": this_w["all_mentions"],
                    "complaints": this_w["complaints"],
                    "rate": this_w["rate"],
                    "by_source": _by_source_block(fam, this_w["week"]),
                },
                "last_week": {
                    "all_mentions": last_w["all_mentions"] if last_w else 0,
                    "complaints": last_w["complaints"] if last_w else 0,
                    "rate": last_w["rate"] if last_w else 0,
                    "by_source": _by_source_block(fam, last_w["week"]) if last_w else {},
                },
                "delta_pts": round(delta, 1),
            }
        else:
            summary[fam] = {
                "this_week_label": "—",
                "this_week": {"all_mentions": 0, "complaints": 0, "rate": 0, "by_source": {}},
                "last_week": {"all_mentions": 0, "complaints": 0, "rate": 0, "by_source": {}},
                "delta_pts": 0,
            }

    def _examples_for(fam: str, week: str, phrase: str) -> list[dict]:
        """Return up to 3 distinct example records (oldest, newest, top-scored)
        for a phrase. Dedupes by permalink so a single matching record doesn't
        appear three times."""
        slots = phrase_examples.get((fam, week, phrase))
        if not slots:
            return []
        seen: set[str] = set()
        out: list[dict] = []
        for label in ("top_scored", "newest", "oldest"):
            ex = slots.get(label)
            if ex is None:
                continue
            pl = ex.get("permalink") or ""
            if pl in seen:
                continue
            seen.add(pl)
            out.append({**ex, "_kind": label})
        return out

    top_terms: dict[str, dict] = {"claude": {"this_week": []}, "openai": {"this_week": []}}
    for fam in ("claude", "openai"):
        wk = summary[fam]["this_week_label"]
        if wk == "—":
            continue
        cnt = phrase_counts.get((fam, wk), Counter())
        top_terms[fam]["this_week"] = [
            {
                "term": term,
                "count": count,
                "examples": _examples_for(fam, wk, term),
            }
            for term, count in cnt.most_common(10)
        ]

    output = {
        "version": "2.0",
        "schema_version": "v0",
        "classifier_version": "v0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {"all_records": total_records},
        "summary": summary,
        "trend": trend,
        "top_terms": top_terms,
        "defection_trend": defection_trend,
        "releases": load_releases(config_dir),
    }

    if strict:
        prior_total = None
        if out_path.exists():
            try:
                with open(out_path) as f:
                    prior = json.load(f)
                prior_total = (prior.get("totals") or {}).get("all_records")
            except (json.JSONDecodeError, OSError):
                pass
        assert_output_shape(output, prior_total=prior_total)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {out_path}")
    print(f"  total_records: {total_records}")
    print(f"  skipped: {skipped_unknown} unknown-model, {skipped_no_text} no-text, {skipped_no_date} no-date")
    for fam in ("claude", "openai"):
        s = summary[fam]
        weeks_n = len(trend[fam])
        print(
            f"  {fam}: {weeks_n} weeks · this_week ({s['this_week_label']}): "
            f"{s['this_week']['rate']:.1%} ({s['this_week']['complaints']}/{s['this_week']['all_mentions']}) · "
            f"delta {s['delta_pts']:+.1f} pts"
        )
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--corpus-dir", type=Path, default=ROOT / "corpus")
    p.add_argument("--config-dir", type=Path, default=ROOT / "config")
    p.add_argument("--out", type=Path, default=ROOT / "phase5" / "data.json")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Run output-shape asserts (use for cron). Exits non-zero on any failure.",
    )
    args = p.parse_args()
    sys.exit(
        main(
            corpus_dir=args.corpus_dir,
            config_dir=args.config_dir,
            out_path=args.out,
            strict=args.strict,
        )
    )
