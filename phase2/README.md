# Phase 2: Taxonomy Derivation

Goal: derive a 15–25 leaf failure-mode taxonomy (rolled up to 5–7 themes) from
the corpus. Two LLMs cluster independently; a third checks for blind spots; a
human reconciles and locks `taxonomy_v1.json`.

Per the brief: LLMs are used **only here**, in one-time chat sessions on the
free tier. Production classification (Phase 3) is regex.

## Layout

```
phase2/
├── README.md              ← this file
├── prompts/               ← prompt templates (committed)
│   ├── clustering.md      ← used by both Claude and Codex passes
│   ├── reconciliation.md  ← merges the two outputs
│   └── noise_floor.md     ← third-model sanity check
├── clustering_input.md    ← generated, gitignored (contains corpus samples)
├── noise_floor_input.md   ← generated, gitignored
├── taxonomy_claude.md     ← Claude output (committed; provenance)
├── taxonomy_codex.md      ← Codex output (committed; provenance)
├── taxonomy_v1_draft.md   ← reconciled draft (committed)
├── judgment_calls.md      ← unresolved items needing human review (committed)
└── taxonomy_v1.json       ← final structured taxonomy (committed)
```

## Workflow

### Step 1 — generate clustering input

```bash
python scripts/phase2_sample.py --mode clustering
# writes phase2/clustering_input.md
```

Sample is balanced across model families (claude / openai / both) and time
buckets, drawing ≥300 records.

### Step 2 — run Claude pass

1. Open https://claude.ai (a fresh chat session, not Claude Code)
2. Paste the entire contents of `phase2/clustering_input.md`
3. Save the response to `phase2/taxonomy_claude.md`

### Step 3 — run Codex pass

1. Open whatever interface you use for Codex / GPT-5
2. Paste the same `phase2/clustering_input.md`
3. Save response to `phase2/taxonomy_codex.md`

### Step 4 — reconcile

1. Take `phase2/prompts/reconciliation.md`, fill in the placeholders with the
   contents of both taxonomies
2. Run in a fresh Claude chat
3. Save output as `phase2/taxonomy_v1_draft.md` and `phase2/judgment_calls.md`
4. **Human review** the judgment calls. Decide each one. Update the draft.

### Step 5 — third-model noise floor check

```bash
python scripts/phase2_sample.py --mode noise_floor
# writes phase2/noise_floor_input.md (100 random records + the locked taxonomy)
```

1. Run in a small different-vendor model (Claude Haiku, GPT-5-mini, Llama via a
   free tier) — the point is independent checking, not redundancy
2. The model lists records that don't fit any category
3. Compute unfit rate. If <30% → taxonomy passes. If ≥30% → revise and re-run

### Step 6 — finalize

Convert the reconciled draft into structured `taxonomy_v1.json`:

```json
{
  "version": "1.0",
  "version_date": "YYYY-MM-DD",
  "themes": [{"id": "capacity_access", "label": "Capacity / access", "leaf_ids": [...]}, ...],
  "leaves": [
    {
      "id": "rate_limits",
      "theme": "capacity_access",
      "definition": "...",
      "distinguishing_test": "...",
      "examples": [{"text": "...", "permalink": "...", "model": "claude"}, ...]
    },
    ...
  ],
  "valence_markers": [
    {"id": "defection", "examples": ["cancelled", "switching to", "done with", ...]},
    {"id": "loyalty", "examples": ["still better than", "saved my project", ...]},
    {"id": "conditional_loyalty", "examples": ["used to love", "hope they fix", ...]}
  ]
}
```

Phase 3 reads this and generates `FAILURE_PATTERNS` + `VALENCE_PATTERNS` regex
dicts. The taxonomy_v1.json itself contains no regex — patterns are a Phase 3
artifact derived from it.

## Validation gates (revised brief §11)

- 15–25 leaf categories, 5–7 themes
- ≥60% theme-level agreement between Claude and Codex passes
- Third-model unfit rate <30%

If any gate fails, revise prompts or sample, re-run.

## Notes

- The clustering prompt explicitly asks the LLM to be honest about edge cases.
  Take that section seriously when reviewing.
- Valence markers (defection / loyalty / conditional loyalty) are tracked
  **separately** from failure modes — they're not a 6th theme.
- Don't tune the taxonomy per-model — same categories apply to claude and
  openai content. The whole point is symmetric comparison.
- Re-classify all corpus records when taxonomy version bumps. Each record
  carries `taxonomy_version` once Phase 3 lands.
