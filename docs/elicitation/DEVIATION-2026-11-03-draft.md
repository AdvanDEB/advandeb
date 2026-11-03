# Draft deviation entry for `advandeb_methods/experiments/DEVIATIONS.md`

**Status: draft.** Written in that file's format: date, what changed, why,
effect on the reported results.

---

## 2026-11-03 — "Disputes" for `contradicts`, and an abstention label (guidelines 2.1)

**Decided by** the project owner, 2026-11-03. **Implemented** in the AdvanDEB
platform, branch `fix/workshop-p0` (guidelines v2.1). **Judgments affected:**
every evidence judgment recorded under guidelines 2.0. They keep their
`guidelines_version: "2.0"` stamp and are not reinterpreted.

### What changed

1. **The `contradicts` passage label reads "Disputes"** on the form, in the
   one-screen introduction and in the calibration editor. Hint: "argues or
   shows against it". The stored value stays `contradicts`, so records under
   2.0 and 2.1 share one schema.
2. **The machine panel's prompt is reworded to match** ("disputes" in place of
   "contradicts") and the panel is re-run on the frozen evidence sets as a new
   adjudicator fingerprint. The 2.0 panel is kept, not overwritten.
3. **A fourth passage label, `cannot_judge`** ("garbled, or outside what you
   can assess"). It counts as a label, so "label every passage" still holds,
   but it carries no evidential role and no score-label conflict. In
   agreement statistics it is a missing value, not a category.

### Why

Experts trying the form said "contradicts" is too strong a word for a
passage that argues against a fact without refuting it, and that raw PDF
passages (line numbers, list fragments) are sometimes unreadable. A forced
label on such a passage is a guess that enters the agreement statistic as if
it were a judgment.

### Effect on the reported results

- **Wording and the human–machine comparison.** "Dispute" is a lower bar than
  "contradict", so the human rate of `contradicts` labels may rise under 2.1.
  The comparison stays like for like only because the machine panel is
  re-run with the same wording. Human 2.0 judgments are compared with the 2.0
  panel and human 2.1 judgments with the 2.1 panel. Pooling across versions
  requires showing that the `contradicts` rate did not shift between them.
- **The machine panel's wording effect is itself a result.** The same
  models on the same frozen passages under both wordings measure how much the
  word alone moves the rare `contradicts` class (2.0 panel: per-class
  α = 0.259).
- **Abstentions.** The `cannot_judge` rate per passage is reported. Passages
  that many experts cannot judge point to unreadable evidence, which bears on
  how the frozen evidence sets were built.
