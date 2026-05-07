# lemon

> **is it just you?**

AI quality is felt, not measured. `lemon` tracks crowd-sourced sentiment for
Claude and Codex on Reddit and HN — one complaint rate per model, weekly,
with trend.

Selection-biased by construction. Classifier undercounts on purpose.
**Trend > absolute level.** [Methodology on the dashboard.](phase5/index.html#methodology)

## Why

When a vendor's quality claims can't be independently verified, your own
perception is unreliable, and benchmarks come from the same companies that
benefit from looking good — aggregated crowd sentiment becomes a crude
substitute for ground truth. Not because it's accurate (it's noisy and
selection-biased) but because it's what's left.

## What it shows

```
   CLAUDE                  CHATGPT / GPT-5 / CODEX
   9%                      8%
   complaints this week    complaints this week
   HN 12% · Reddit 9%      HN 7% · Reddit 8%
   ▼ 0.1 pts from last     ▼ 0.8 pts from last
```

Plus a 90-day trend with release-event annotations, the top 10 phrases driving
this week's complaints (each with up to 3 example permalinks you can click through
to read), and a separate small chart for "switching to / cancelled / done with"
rhetoric — labeled rhetoric, not behavior.

## What it isn't

- Not a counter-benchmark, satisfaction metric, or fairness audit
- Not a measurement of actual user churn — defection language is rhetoric
- Not a fine-grained failure-mode taxonomy

## Run it locally

```bash
pip install -e .
python scripts/healthcheck.py            # confirm data sources reachable
python scripts/run_phase1.py             # 12-month corpus pull (~hours)
python scripts/v0_classify.py            # apply phrase list → phase5/data.json
python scripts/build_standalone.py       # build a single-file HTML snapshot
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

## Architecture

- **Corpus pull** (HN Algolia + Reddit historical via arctic_shift): runs
  locally and on a 4-hour GitHub Actions cron.
- **v0 classifier** (phrase-list): runs in ~30 seconds against ~350k records.
- **Dashboard**: static site, single page, vanilla HTML/CSS/JS, dark monospace.
  Deployed via GitHub Pages.
- **Cron** commits `phase5/data.json` on each refresh; the dashboard reads it
  at page load with a staleness banner if data ages past 8 hours.

## Layout

```
lemon/
├── config/                  hand-curated knobs (phrases, subreddits, releases)
├── scrapers/                HN + Reddit collectors
├── scripts/                 healthcheck, orchestrator, classifier, stats
├── phase5/                  dashboard (static site, served by GH Pages)
├── docs/                    methodology + roadmap notes
├── .github/workflows/       refresh + reclassify crons
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
6. **Reddit data lags ~24–48 hours.** GH Actions runner IPs are blocked from
   Reddit's unauth JSON endpoint, so Reddit posts come in via arctic-shift's
   third-party archive. HN data is real-time.
7. **Twitter/X is missing.** Free-tier API closed in 2023; not within the
   project's zero-recurring-cost budget.
8. **Volume is asymmetric.** ChatGPT/Codex are mentioned far more than Claude.
   All rates are normalized per mention.
