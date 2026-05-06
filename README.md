# lemon

> **is it just you, or is it actually bad right now?**

Sentiment-rate barometer for Claude and ChatGPT/GPT-5/Codex. Tracks the rate
at which public forums (Reddit, HN) post complaint-valence mentions of each
model, weekly, with trend. Selection-biased by construction; methodology
prominent on the dashboard.

## What this is

A single number per model, updated weekly:

> **42% of Claude mentions this week are complaints** — up from 31% last week.

Plus a trend line (90 days), plus the top words people are using when they
complain, plus a defection-rhetoric line (labeled as *rhetoric*, not behavior).

That's the whole product.

## What this is NOT

- Not a counter-benchmark or fairness audit
- Not a satisfaction metric (it's complaint volume in *complaint forums*)
- Not a measurement of actual user churn (defection language is rhetoric)
- Not a fine-grained failure-mode taxonomy — that work was deferred (see
  `docs/PIVOT-2026-05-06.md` for why)

## Status

Phase 1 (corpus pull): mostly done. HN: 73k records. Reddit historical:
partial.
Phase 5 (dashboard): prototype with mock data.
Phase 3 (classifier — curated phrase list + word frequency): pending.
Phase 4 (live scrapers + GitHub Action): pending.

See [`CLAUDE.md`](CLAUDE.md) for the locked v0 scope and constraints.

## Layout

```
lemon/
├── CLAUDE.md            agent instructions, locked scope
├── config/              hand-curated knobs
├── scrapers/            HN + Reddit corpus collectors
├── scripts/             healthcheck, orchestrator, stats
├── phase5/              dashboard (static site)
├── docs/                pivot history + archived v1 ideas
└── corpus/              scraped NDJSON (gitignored)
```

## Quickstart

```bash
pip install -e .
python scripts/healthcheck.py
python scripts/run_phase1.py           # full 12-month corpus pull
python scripts/corpus_stats.py         # validation gate
```

Dashboard preview:

```bash
cd phase5 && python3 -m http.server 8766
# open http://localhost:8766
```

## Methodology

Disclosed on the dashboard itself, not buried.

1. **Selection bias.** People who are angry post; people who are satisfied
   don't. The data is a complaint distribution, not a satisfaction metric.
2. **Defection language is rhetoric, not behavior.** "Switching to,"
   "cancelled" track expressed sentiment. They do not measure churn.
3. **Two-horse race tracks release calendars.** Spikes correlate with
   contentious launches. Toggle the x-axis to "weeks since release" to compare
   models without launch confounding.
4. **The classifier undercounts.** Curated phrase list ships transparency over
   recall. The trend captures direction; the absolute level is conservative.
5. **Twitter/X is missing.** Free-tier API access closed in 2023. Bluesky
   covers a sliver but is journalist-skewed.
6. **Volume is asymmetric.** ChatGPT/Codex get mentioned far more than Claude.
   All numbers are *per 1k mentions*, never raw counts.
