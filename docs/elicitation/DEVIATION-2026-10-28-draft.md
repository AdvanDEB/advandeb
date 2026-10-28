# Draft deviation entry for `advandeb_methods/experiments/DEVIATIONS.md`

**Status: draft. Not yet added to `advandeb_methods`** — that repository is
edited only with the project owner's OK. Written in that file's format: date,
what changed, why, effect on the reported results.

---

## 2026-10-28 — Expert elicitation reshaped before any judgment was collected

**Decided by** the project owner, 2026-10-28. **Implemented** in the AdvanDEB
platform, branch `feat/elicitation-reshape` (guidelines v2.0). **Judgments
affected: none** — production held 0 elicitation records when the change was
made, so no collected data is reinterpreted.

### What changed, against `docs/02-elicitation-protocol.md`

1. **One human arm, H-EK only.** Experts judge each stylized fact from the
   frozen passages *and* their own knowledge (`docs/14` §2, "expert judges as
   an expert"). The H-K arm (statement and knowledge alone) is not collected,
   and the instruction that previously asked experts to "set aside what you
   know beyond the passages" is withdrawn. Passage labels (T1) are still asked
   *by what the passage says*, with the agents' axes and wording; the two
   fact-level scores (T2) are the expert's own judgment.
2. **Departure question and conditional rationale.** Every judgment records
   `departs_from_passages` — *"Does your judgment go beyond or against what
   these passages show?"* — the human counterpart of M-EK's
   passage/memory attribution (`docs/14` §2.1). A rationale is required only
   when the answer is yes, or when the expert's overall scores contradict
   their own passage labels (consensus 3 with no `supports`, consensus 1 with
   no `contradicts`, strength ≥ 2 with no `supports`). Previously a rationale
   was required on every judgment. The machine assessment plays no part in the
   rule and is not shown.
3. **Calibration.** The 15 adjudicated pilot cases of `docs/02` §7 (as built:
   15 generated provenance/scope cases) are replaced by **three to five real
   evidence items chosen by the team**, each with an agreed reference answer
   and explanation, versioned. Experts are not held up while no set is
   published; judgments made before calibration are stamped
   `calibration_version: null`. Once a set is published each expert works it
   once; there are no scheduled repeats to measure drift. **A fact used for
   calibration leaves the measured queue** for every expert.
4. **No day-one tasks.** T4 provenance tracing and the scope and
   assessability tasks (3,786 queued items) are no longer served. Their queue
   rows and code are kept.
5. **Passages shown with full citations** (authors, year, title, journal,
   DOI), resolved at serve time from the curated document metadata; the frozen
   passages and every hash are unchanged. The corpus of origin stays hidden
   (`docs/02` §5).
6. **Expert judgments feed the knowledge base**: the panel's aggregated
   verdict (minimum 3 judgments; contributor-tier shown separately) is shown
   next to each fact, withheld from anyone who may still judge that fact.
   Expert-named references become curator-reviewed *candidates*; they never
   move a score (`docs/09` §2.5 unchanged).

### Why

The protocol was drafted without the project owner's sign-off on these
points, and the built flow — two arms with different rules about what an
expert may use, a rationale on every item, a calibration set unrelated to the
task — confused the owner and would confuse the panel. The purpose of the
elicitation is twofold: inter-expert agreement for the methods paper and an
expert contribution to the knowledge base. H-EK serves both; H-K serves only
the first.

### Effect on the reported results

- **Lost contrasts.** `H-EK − H-K` ("what does evidence add to an expert?")
  and the interaction row of `docs/14` §2.2 ("does evidence help machines
  more than experts?") cannot be computed from this elicitation. The
  headline comparison `H-EK vs M-EK` is unaffected and becomes the only
  human–machine comparison.
- **The H-EK arm is now a different instrument from the `matched` arm of
  `docs/09` §5.2** as originally worded (judge only from the passages). Report
  the human ceiling as an H-EK ceiling. Because passage labels are still asked
  by what the passage says, passage-level α remains comparable with the
  machine panel's; fact-level scores should be compared with `M-EK`, not
  `M-E`.
- **Rationale coverage is selective by design.** Rationales exist for
  judgments that depart from the passages; their absence is informative, not
  missing data. `departs_from_passages` and `score_label_conflicts` are
  reported alongside (rate of departure per category, per expert).
- **Sampling frame.** Calibration facts (3–5 of the 62 evidence facts) are
  removed from measurement: the comparison corpus loses 3–5 items × 5 panel
  judgments. The frame is reported as 62 minus the calibration facts, named.
- **Calibration as a covariate.** `calibration_version` is stamped on every
  judgment; pre-calibration judgments are reported separately or as a
  covariate, never silently pooled.
- **No drift measurement** from repeated calibration cases.
- **Metadata not collected.** No expert provenance (T4), scope or
  assessability judgments; the collection's provenance record and the
  scope-adequacy analysis (`docs/06` §6.1a) rely on other sources.
- **Citations visible.** Experts see who wrote each passage. This can make
  `restatement` easier to recognise (e.g. a Kooijman monograph restating the
  theory); agents saw the passage text with at most a file name. Reported as a
  presentation difference between the panels.
- **Anchoring.** No machine output is shown at all in first-round
  elicitation (previously the legacy 1–100 score was available behind a
  logged disclosure), so the anchoring sub-experiment of `docs/02` §5, if run,
  needs its own arm.
