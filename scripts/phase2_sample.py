"""Generate a corpus sample for Phase 2 LLM passes.

Two modes:
  --mode clustering   → 300 records balanced across {claude, openai, both} and
                        time buckets, ready to paste into clustering.md prompt
  --mode noise_floor  → 100 random records (no balancing); needs an existing
                        taxonomy_v1.json to embed alongside

Output goes to phase2/clustering_input.md or phase2/noise_floor_input.md.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_corpus_records(corpus_dir: Path) -> list[dict]:
    out = []
    for shard in sorted(corpus_dir.rglob("*.ndjson")):
        with open(shard) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def time_bucket(date_iso: str, n_buckets: int = 4) -> int:
    """Map ISO date to a time-bucket index 0..n_buckets-1.

    The buckets divide the global date range across all records, computed at
    sampling time. We pass-in the already-computed extents to avoid a second
    full scan.
    """
    return 0  # placeholder; actual logic in sample_balanced


def sample_balanced(
    records: list[dict],
    n_total: int,
    n_buckets: int = 4,
    posts_share: float = 0.20,
) -> list[dict]:
    """Stratified sample: balanced across model × time × kind (post vs comment).

    Comments dominate the corpus by ~100x; proportional sampling buries posts.
    We allocate `posts_share` of the budget to posts, rest to comments.
    """
    useful = [r for r in records if r.get("model_mentioned") in ("claude", "openai", "both")]
    if not useful:
        return []

    posts_budget = int(n_total * posts_share)
    comments_budget = n_total - posts_budget

    posts = [r for r in useful if not r.get("is_comment")]
    comments = [r for r in useful if r.get("is_comment")]

    # If we don't have enough posts, take what's available and reallocate the rest
    if len(posts) < posts_budget:
        posts_budget = len(posts)
        comments_budget = n_total - posts_budget

    months = sorted({r.get("date", "")[:7] for r in useful if r.get("date")})
    month_to_bucket: dict[str, int] = {}
    for i, m in enumerate(months):
        month_to_bucket[m] = min(int(i * n_buckets / max(len(months), 1)), n_buckets - 1)

    def stratified_pick(pool: list[dict], budget: int) -> list[dict]:
        """Stratify by (source × model × time_bucket). Source is included so a
        small minority source still shows up in the sample even when the other
        source dominates."""
        if not pool or budget <= 0:
            return []
        cells: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
        for r in pool:
            key = (
                r.get("source"),
                r.get("model_mentioned"),
                month_to_bucket.get(r.get("date", "")[:7], 0),
            )
            cells[key].append(r)
        n_cells = len(cells)
        per_cell = max(1, budget // n_cells)
        picked: list[dict] = []
        leftover: list[dict] = []
        for recs in cells.values():
            random.shuffle(recs)
            take = min(per_cell, len(recs))
            picked.extend(recs[:take])
            leftover.extend(recs[take:])
        if len(picked) < budget and leftover:
            random.shuffle(leftover)
            picked.extend(leftover[: budget - len(picked)])
        return picked[:budget]

    out = stratified_pick(posts, posts_budget) + stratified_pick(comments, comments_budget)
    random.shuffle(out)
    return out[:n_total]


def render_record(r: dict, idx: int) -> str:
    src = r.get("source", "?")
    sub = r.get("source_subkey", "?")
    date = r.get("date", "")[:10]
    model = r.get("model_mentioned", "?")
    permalink = r.get("permalink", "")
    score = r.get("score", 0)
    is_comment = r.get("is_comment", False)
    kind = "comment" if is_comment else "post"
    text = (r.get("post_text") or "").strip()
    # Trim very long texts so the paste-able input stays under ~50k tokens
    if len(text) > 1500:
        text = text[:1500] + "  …[truncated]"
    return (
        f"### Record {idx}  [{src}/{sub}]  {date}  model={model}  {kind}  score={score}\n"
        f"Permalink: {permalink}\n\n"
        f"{text}\n"
    )


def write_clustering_input(corpus_dir: Path, out_path: Path, prompt_path: Path, n: int = 300) -> int:
    records = load_corpus_records(corpus_dir)
    print(f"Loaded {len(records)} records from {corpus_dir}")
    sample = sample_balanced(records, n_total=n)
    print(f"Sampled {len(sample)} records (balanced across model × time)")

    # Render
    blocks = [render_record(r, i + 1) for i, r in enumerate(sample)]
    sample_text = "\n---\n\n".join(blocks)

    template = prompt_path.read_text()
    out_path.write_text(template.replace("{SAMPLE}", sample_text))
    print(f"Wrote {out_path}")
    print(f"  Sample summary:")
    by_model = defaultdict(int)
    by_month = defaultdict(int)
    by_kind = defaultdict(int)
    by_source = defaultdict(int)
    for r in sample:
        by_model[r.get("model_mentioned", "?")] += 1
        by_month[r.get("date", "")[:7]] += 1
        by_kind["comment" if r.get("is_comment") else "post"] += 1
        by_source[r.get("source", "?")] += 1
    print(f"    by source: {dict(by_source)}")
    print(f"    by model:  {dict(by_model)}")
    print(f"    by kind:   {dict(by_kind)}")
    print(f"    months covered: {len(by_month)} ({sorted(by_month.keys())[0]}..{sorted(by_month.keys())[-1]})")
    return 0


def write_noise_floor_input(
    corpus_dir: Path,
    out_path: Path,
    prompt_path: Path,
    taxonomy_path: Path,
    n: int = 100,
) -> int:
    if not taxonomy_path.exists():
        print(f"Missing {taxonomy_path}. Run clustering + reconciliation first.", file=sys.stderr)
        return 1

    records = load_corpus_records(corpus_dir)
    useful = [r for r in records if r.get("model_mentioned") in ("claude", "openai", "both")]
    sample = random.sample(useful, min(n, len(useful)))
    print(f"Sampled {len(sample)} records for noise check")

    blocks = [render_record(r, i + 1) for i, r in enumerate(sample)]
    sample_text = "\n---\n\n".join(blocks)

    template = prompt_path.read_text()
    taxonomy = taxonomy_path.read_text()
    filled = template.replace("{TAXONOMY}", taxonomy).replace("{RECORDS}", sample_text)
    out_path.write_text(filled)
    print(f"Wrote {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["clustering", "noise_floor"], required=True)
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "corpus")
    parser.add_argument("--phase2-dir", type=Path, default=ROOT / "phase2")
    parser.add_argument("--n", type=int, default=None,
                        help="Sample size override. Defaults: 300 for clustering, 100 for noise_floor")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)

    if args.mode == "clustering":
        return write_clustering_input(
            corpus_dir=args.corpus_dir,
            out_path=args.phase2_dir / "clustering_input.md",
            prompt_path=args.phase2_dir / "prompts" / "clustering.md",
            n=args.n or 300,
        )
    else:
        return write_noise_floor_input(
            corpus_dir=args.corpus_dir,
            out_path=args.phase2_dir / "noise_floor_input.md",
            prompt_path=args.phase2_dir / "prompts" / "noise_floor.md",
            taxonomy_path=args.phase2_dir / "taxonomy_v1.json",
            n=args.n or 100,
        )


if __name__ == "__main__":
    sys.exit(main())
