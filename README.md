# lemon

> **is it just you, or is it actually bad right now?**

Public sentiment for Claude and ChatGPT/GPT-5/Codex. One number per model
each week — the share of public mentions classified as complaints — with
trend, top phrases, and defection rhetoric.

Selection-biased by construction. Classifier undercounts on purpose.
**Trend > absolute level.** [Methodology on the dashboard.](phase5/index.html#methodology)

## What it shows

```
   CLAUDE                  CHATGPT / GPT-5 / CODEX
   13%                     8%
   complaints this week    complaints this week
   HN 15% · Reddit 13%     HN 8% · Reddit 7%
   ▲ 3.2 pts from last     ▼ 0.9 pts from last
```

Plus a 90-day trend with release-event annotations, the top 10 phrases driving
this week's complaints (each with 3 example permalinks you can click through
to read), and a separate small chart for "switching to / cancelled / done with"
rhetoric — labeled rhetoric, not behavior.

## What it isn't

- Not a counter-benchmark, satisfaction metric, or fairness audit
- Not a measurement of actual user churn — defection language is rhetoric
- Not a fine-grained failure-mode taxonomy (deferred — see [`docs/PIVOT-2026-05-06.md`](docs/PIVOT-2026-05-06.md))

## Run it locally

```bash
pip install -e .
python scripts/healthcheck.py            # confirm data sources reachable
python scripts/run_phase1.py             # 12-month corpus pull (~hours)
python scripts/v0_classify.py            # apply phrase list → phase5/data.json
python scripts/build_standalone.py       # writes self-contained ~/Desktop/lemon.html
```

Dashboard preview:

```bash
cd phase5 && python3 -m http.server 8766    # open http://localhost:8766
```

## How the classifier works

A record is counted as a complaint if its text contains any phrase from
[`config/complaint_phrases.json`](config/complaint_phrases.json). The list is
hand-curated, ships transparency over recall, and applies identically to both
model families. The top phrases shown on the dashboard are literal entries
from that list — every term is auditable.

No ML. No off-the-shelf sentiment models (they misclassify dev-context
language constantly). The trade is simpler: the absolute level under-counts;
the trend captures direction.

## Project state

- **Corpus pull** (HN + Reddit historical via arctic_shift + reddit recent
  via unauthenticated JSON endpoints): operational; runs locally
- **v0 classifier**: phrase-list based, runs in ~30 seconds against ~190k records
- **Dashboard**: static site, single page, vanilla HTML/CSS/JS, dark monospace
- **Live deployment** (GitHub Action cron + Pages): pending —
  [see launch plan](docs/v0.1-launch-plan.md)

## Layout

```
lemon/
├── CLAUDE.md                agent instructions, locked v0 scope
├── config/                  hand-curated knobs (phrases, subreddits, releases)
├── scrapers/                HN + Reddit collectors
├── scripts/                 healthcheck, orchestrator, classifier, stats
├── phase5/                  dashboard (static site)
├── docs/                    pivot history + launch plan + audit notes
└── corpus/                  scraped NDJSON (gitignored)
```

## Methodology summary

(Full version on the dashboard itself.)

1. **Selection-biased by construction.** People who are angry post; people who
   are satisfied don't. The complaint rate is a property of *complaint forums*,
   not of all users.
2. **The classifier undercounts.** Phrase list trades recall for transparency;
   read the trend, not the absolute number.
3. **Defection language is rhetoric, not behavior.** "Switching to," "cancelled"
   are sentiment markers. They do not measure churn.
4. **Two-horse race tracks release calendars.** Toggle the x-axis to "weeks
   since release" to compare without launch confounding.
5. **Same phrase list, both models.** No per-model tuning.
6. **Twitter/X is missing.** Free-tier API closed in 2023; not within the
   project's zero-recurring-cost budget.
7. **Volume is asymmetric.** ChatGPT/Codex are mentioned far more than Claude.
   All rates are normalized per mention.

## Pivots and decisions

This was originally framed as a counter-benchmark with a fine-grained failure
taxonomy. After review, the actual user need was simpler — *am I being
gaslit?* — which is answered by a single rate with a trend, not a categorical
breakdown. The taxonomy work is archived at
[`docs/_archive/v1_taxonomy_proposal/`](docs/_archive/v1_taxonomy_proposal/).
Full pivot rationale: [`docs/PIVOT-2026-05-06.md`](docs/PIVOT-2026-05-06.md).
