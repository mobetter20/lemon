# lemon

AI Model Reality Check — counter-dashboard for what AI labs claim vs what users report breaking.

> "What they claim vs what people report breaking — and where they're voting with their feet."
>
> Defection language is tracked as **rhetorical sentiment**, not measured behavior.
> The dataset is selection-biased by construction (complaint forums); see Methodology when
> the dashboard ships.

## State

Phase 1 (corpus pull) — scaffolding in place.
Phases 2–5 not yet started.

## Layout

```
lemon/
├── config/                     hand-curated knobs
│   ├── subreddits.json         subreddits + percentile/floor selection strategy
│   ├── hn_queries.json         HN Algolia queries + point thresholds
│   ├── model_keywords.json     for model_mentioned detection
│   └── releases.json           release calendar (populate before Phase 5)
├── scrapers/
│   ├── common.py               schema, model detection, dedup, NDJSON I/O
│   ├── hn.py                   HN Algolia
│   ├── reddit_historical.py    pullpush primary, arctic_shift fallback
│   └── reddit_recent.py        PRAW (last ~30 days, fills pullpush lag)
├── scripts/
│   ├── healthcheck.py          source reachability + mode decision
│   ├── run_phase1.py           orchestrator
│   └── corpus_stats.py         validation gate
└── corpus/                     NDJSON output, gitignored in Phase 1
```

## Quickstart

```bash
# From the project root
pip install -e .

# Optional: PRAW credentials (covers ~last 30 days where pullpush lags)
# Create a script-type Reddit app at https://www.reddit.com/prefs/apps
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
export REDDIT_USER_AGENT="lemon-corpus-builder/0.1 (by /u/<your-handle>)"

# 1) Health-check
python scripts/healthcheck.py

# 2) Smoke test (2 months, HN only)
python scripts/run_phase1.py --months-back 2 --skip-reddit-historical --skip-reddit-recent

# 3) Full run (~hours)
python scripts/run_phase1.py

# 4) Validate
python scripts/corpus_stats.py
```

To re-scrape from scratch:

```bash
rm -rf corpus/* corpus/.dedup.db
```

## Schema

Every NDJSON line:

```json
{
  "source": "hn|reddit",
  "source_subkey": "hn-thread-12345 | r/ClaudeAI",
  "post_id": "...",
  "permalink": "...",
  "date": "ISO 8601 UTC",
  "model_mentioned": "claude|openai|both|unknown",
  "post_text": "...",
  "score": 12,
  "is_comment": false,
  "parent_id": null,
  "mentions_release_event": null,
  "scraped_at": "ISO 8601 UTC",
  "scraper_version": "1.0"
}
```

## Phase 1 validation gates

`scripts/corpus_stats.py` exits non-zero unless:

- Records ≥ 5,000 (full) or ≥ 2,000 (degraded — flagged)
- Date range ≥ 6 months
- Each model family ≥ 30%, no skew worse than 70/30

Soft warning if < 3 release events covered (until `releases.json` populated).

## Decisions locked

- **Storage**: date-sharded by source (`corpus/<source>/<YYYY-MM>.ndjson`)
- **Reddit selection**: top-20% by score per (subreddit, month), absolute floor 5
- **Comment scope**: Reddit — top-level + nested where score ≥ 3. HN — text-length ≥ 20 (HN does not expose comment scores).
- **Bluesky**: deferred to Phase 4 (live-only, not historical)
- **Dedup**: `(source, permalink)` keyed; SQLite index at `corpus/.dedup.db`

## Mode logic

`healthcheck.py` exits:
- `0` full — HN + at least one Reddit historical source up
- `1` fail — HN down (cannot proceed)
- `2` degraded — HN up, both Reddit historical sources down → 2k target, HN + PRAW recent only

## Known caveats

- **HN comment scores**: HN doesn't expose comment scores via Algolia. Filter by text length instead.
- **Reddit historical reliability**: pullpush and arctic_shift both depend on third-party infrastructure that has had outages since the 2023 API change. Re-run healthcheck before each session.
- **PRAW credentials**: optional but recommended — covers the ~24h lag in pullpush coverage.
- **Dedup is single-run**: clear `corpus/.dedup.db` and `corpus/*` to re-scrape.
