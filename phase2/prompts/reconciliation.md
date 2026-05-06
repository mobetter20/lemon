# Taxonomy Reconciliation

I have two failure-mode taxonomies derived from the same corpus by two
different LLMs (one Claude, one Codex/GPT). Both are pasted below.

## Your task

Produce a unified taxonomy by:

1. **Mapping equivalence.** For each leaf in Taxonomy A, find its B
   counterpart. Flag categories appearing in only one.

2. **Diff classification.** For each disagreement, classify as:
   - **Boundary disagreement** (same phenomenon, different cut lines)
     → propose merge or finer split
   - **Coverage gap** (one taxonomy missed a real failure mode)
     → include it
   - **Spurious category** (one taxonomy invented a category from surface
     features) → exclude it
   - **Genuine judgment call** → flag for human, do NOT auto-resolve

3. **Output unified taxonomy** in the same format as inputs, with a column
   noting provenance: `[A only / B only / both / merged / split]`.

4. **List unresolved judgment calls at the end.** Do not guess — these are
   for the human reviewer.

## Output format

Two sections:

### Unified taxonomy (draft)

[Same per-leaf format as the input taxonomies, plus a `Provenance:` line
on each leaf.]

### Judgment calls

[Numbered list of unresolved items. For each:
- What the disagreement is
- Why you couldn't auto-resolve it
- The 2–3 plausible resolutions and what each implies
- A recommendation if you have one (and a one-sentence why)]

---

## Taxonomy A (Claude)

{TAXONOMY_A}

---

## Taxonomy B (Codex / GPT)

{TAXONOMY_B}
