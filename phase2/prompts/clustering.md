# Failure Mode Clustering Task

You are analyzing a corpus of public complaints about AI coding/chat assistants
(Claude, Claude Code, ChatGPT, Codex, GPT-5) scraped from Reddit and HN.

The records are embedded below in the **Corpus Sample** section. Each record
includes its source, date, the model family it mentions, and the post or
comment text. Treat the sample as representative of the full corpus.

---

## Your task

Derive a failure-mode taxonomy from this data. Do **not** impose categories
from prior knowledge — let categories emerge from what people actually
complain about.

## Hard requirements

1. **Read broadly before clustering.** Sample at least 300 records across
   different time periods and both model families before proposing categories.
   The sample below is already balanced across model families and time —
   skim widely, don't anchor on the first thing you read. Note your sampling
   method in the "Sampling notes" section.

2. **Cluster by underlying problem, not vocabulary.** Two complaints belong
   together if fixing them would require the same kind of change.
   "Hit rate limit" and "usage cap exceeded" = same cluster.
   "Refused to write code" and "wrote placeholder TODO" = possibly same
   (laziness) or different (refusal vs incompleteness) — make the call,
   justify it.

3. **Target granularity: 15–25 leaf categories, rolled up into 5–7 themes.**
   More than 25 leaves = clustering at vocabulary level. Fewer than 15 =
   over-abstracting.

4. **Equal attention to both model families.** Sample roughly equal numbers
   of Claude-tagged and OpenAI-tagged complaints during derivation, even if
   corpus is unbalanced. Otherwise taxonomy detects one family's issues
   better than the other's.

5. **Track valence markers as a SEPARATE parallel category, not a failure
   mode.** This is high-signal sentiment data. Three subcategories:
   - **Defection language**: "cancelled," "switching to," "done with," "going back to"
   - **Loyalty language**: "still better than," "saved my project," "best AI"
   - **Conditional loyalty**: "used to love," "hope they fix," "gave it another try"

   Note: these are markers of *expressed sentiment*, not of measured user
   behavior. Label them in the output as "rhetoric of X" not "X behavior."

6. **Reject your own first instinct on ambiguous cases.** If a complaint
   could fit two categories, that's a signal categories may be wrong. Note
   these — they test taxonomy quality.

## Output format

For each leaf category:

### [Category name]
- **Theme**: [parent theme]
- **Definition**: [1–2 sentences]
- **Distinguishing test**: [what makes a complaint THIS vs adjacent ones]
- **Example quotes**: [5 verbatim excerpts, ideally 3 about one model + 2
  about the other, with permalinks]
- **Estimated prevalence**: [rough % of complaints in this bucket — across
  the full sample, not just this section]
- **Edge cases / ambiguity**: [where this bleeds into others]

Then:

### Theme rollup
[5–7 themes, each listing leaf categories + 1-sentence theme description]

### Valence markers
[Same format as failure modes, but flagged as parallel category. Include
defection / loyalty / conditional-loyalty subcategories with example
phrases. Note that these are *rhetoric* markers, not behavioral evidence.]

### Cases your taxonomy handles poorly
[Be honest. List 3–5 complaint types your categories don't fit cleanly.
**This is the most important section** — it tests whether you've over-fitted
or papered over real ambiguity.]

### Sampling notes
[How you sampled, time range, model split, biases noticed in the corpus
itself.]

## What I do NOT want

- Sentiment polarity buckets (positive/negative/neutral) — useless.
- Abstract categories like "quality issues" or "user experience" — they
  don't drive any decisions.
- Categories defined by which model is being complained about — same
  failure mode in different models is the same category.
- Made-up examples — every quote must be a real excerpt with the permalink
  from the corpus below.
- Confident taxonomy with no acknowledgment of edge cases.

---

## Corpus Sample

{SAMPLE}
