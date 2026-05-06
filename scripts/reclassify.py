"""Reclassify model_mentioned for comments using parent inheritance.

Walks all NDJSON shards in corpus/. Builds a global id -> model map across all
records. For each comment with model_mentioned='unknown', walks the parent_id
chain to find the first non-unknown ancestor's model and overwrites.

Atomic per-shard: writes to <shard>.new, then renames over the original.

Run after a scrape if comments were classified before the parent-inheritance
logic landed (Phase 1 historical fix).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize_id(rid: str | None) -> str:
    """Strip Reddit fullname prefix (t1_, t3_) if present."""
    if not rid:
        return ""
    if len(rid) > 3 and rid[:3] in ("t1_", "t3_"):
        return rid.split("_", 1)[1]
    return rid


def main(corpus_dir: Path = ROOT / "corpus") -> int:
    shards = sorted(corpus_dir.rglob("*.ndjson"))
    if not shards:
        print(f"No NDJSON files in {corpus_dir}")
        return 1

    # Pass 1: build id -> model and id -> parent maps from all records
    id_to_model: dict[str, str] = {}
    id_to_parent: dict[str, str] = {}
    n_pass1 = 0
    print(f"Pass 1/2: indexing {len(shards)} shards...")
    for shard in shards:
        with open(shard) as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                rid = normalize_id(rec.get("post_id", ""))
                if rid:
                    id_to_model[rid] = rec.get("model_mentioned") or "unknown"
                    id_to_parent[rid] = normalize_id(rec.get("parent_id"))
                n_pass1 += 1
    print(f"  indexed {n_pass1} records, {len(id_to_model)} unique ids")

    def resolve_inherited(parent_id_raw: str | None) -> str:
        cur = normalize_id(parent_id_raw)
        seen: set[str] = set()
        while cur and cur not in seen:
            seen.add(cur)
            m = id_to_model.get(cur)
            if m and m != "unknown":
                return m
            cur = id_to_parent.get(cur, "")
        return "unknown"

    # Pass 2: rewrite comments with unknown → inherited
    print("Pass 2/2: rewriting shards with inheritance...")
    n_total = 0
    n_changed = 0
    for shard in shards:
        new_shard = shard.with_suffix(shard.suffix + ".new")
        with open(shard) as fin, open(new_shard, "w", encoding="utf-8") as fout:
            for line in fin:
                if not line.strip():
                    fout.write(line)
                    continue
                rec = json.loads(line)
                n_total += 1
                if rec.get("is_comment") and (rec.get("model_mentioned") or "unknown") == "unknown":
                    inherited = resolve_inherited(rec.get("parent_id"))
                    if inherited != "unknown":
                        rec["model_mentioned"] = inherited
                        n_changed += 1
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        new_shard.replace(shard)

    pct = n_changed * 100 / max(n_total, 1)
    print(f"\nReclassified {n_changed} / {n_total} records ({pct:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
