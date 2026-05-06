# Taxonomy Noise-Floor Check

You are evaluating a failure-mode taxonomy on independently-sampled records
to detect blind spots. **You are NOT proposing categories** — only checking
whether the existing ones cover the data.

## Inputs

1. The locked taxonomy (below as **Taxonomy v1**)
2. 100 random records from the corpus (below as **Records**)

## Your task

For each record, decide whether it fits cleanly into one of the existing
leaf categories.

A record "fits" if its underlying complaint matches a leaf's definition AND
distinguishing test. Surface vocabulary alone doesn't make it fit.

A record "doesn't fit" if:
- It's clearly about a failure mode but doesn't match any leaf
- It's ambiguous between two leaves and the taxonomy gives no clear test
- It's a coherent complaint but the taxonomy treats its category as out-of-scope

## Output format

```
Total records evaluated: 100
Unfit count: N
Unfit rate: N%

## Unfit records

1. [permalink] | [model] | [first 80 chars of text]
   → Why doesn't fit: [one sentence]
   → Closest leaf if any: [leaf name or "none"]

2. ...
```

Then:

### Pattern in the unfit set
[1–3 sentence summary. Are the unfit records concentrated in a particular
failure mode the taxonomy missed? Or scattered noise?]

### Recommendation
[One of:
- "Taxonomy passes — unfit rate <30% and no clear missed category"
- "Taxonomy fails on coverage — missed category: [name + definition]"
- "Taxonomy fails on definition — leaf [X] is too narrow / too broad"]

---

## Taxonomy v1

{TAXONOMY}

---

## Records

{RECORDS}
