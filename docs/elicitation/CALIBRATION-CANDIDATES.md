# Calibration examples — candidates for the team

**Status: proposal. The choice, the reference answers and the explanations are
the team's.** Enter the chosen set under `/admin/experts` → *Calibration
examples* (draft → publish). Nothing is gated until a set is published.

## What a good set does

Three to five real evidence items, each teaching one thing an expert must get
right on every item, together covering the answers the form allows:

| Lesson | Why it needs an example |
|---|---|
| Clear support, and *restatement vs primary evidence* | Most DEB support restates the theory (restatement ratio 0.474). The role labels only mean something if experts draw that line alike. |
| A fact the literature contradicts | `contradicts` is the rare, interesting class; consensus 1 must feel like a real answer. |
| Balanced or mixed evidence | *Inconclusive* is a judgment, not a refusal. |
| Every passage neutral, but the expert knows the field | The departure question: *yes, my judgment goes beyond the passages* — with a reason and a reference. |

## The cost

A calibration fact is shown with its answer, so it **leaves the measured
queue for every expert** — both corpora. Each example therefore removes one of
the 62 evidence facts from the comparison (one DEB item × 5 panel judgments,
plus one reproduction item). Five examples: 57 measured facts.

## Candidates (DEB-literature evidence sets)

Profile = how the two machine-panel models (gpt-oss 120b, Claude) labelled
the 18 passages, majority per passage, and on how many passages they agreed.
Used only to find teaching cases; experts never see it.

| # | Fact | Profile (supports / contradicts / neutral · agreement) | Teaches |
|---|---|---|---|
| 1 | **1201** — Many species (most animals and plants) have an embryo stage that does not feed. | 16 / 0 / 2 · 17/18 | Clear support. Check how many supporting passages restate the rule rather than test it: the *evidential role* is the real exercise. |
| 2 | **1221** — In some species energy committed per offspring does not depend significantly on the nutritional status of the mother. | 1 / 8 / 9 · 15/18 | A fact the passages mostly contradict (compare 1220, maternal effects on egg size); *against* as a real answer. |
| 3 | **1230** — Cells in a tissue are metabolically similar regardless of the size of the organism. | 5 / 6 / 7 · 16/18 | Mixed evidence → *inconclusive*; scope (which tissues, which taxa) drives disagreement. |
| 4 | **1239** — Growth decreases with decreasing DO level, due to reduced energy uptake and/or increased expenditure. | 0 / 0 / 18 · 12/18 | No passage bears on it, yet hypoxia reducing growth is well established: the *departure* example — reason plus reference. |
| 5 | **1206** — Length of isomorphic organisms at abundant food follows the von Bertalanffy growth curve. | 12 / 0 / 6 · 18/18 | Strong apparent support; check how much of it is model derivation: *derivation* vs *primary evidence*, and strength. |
| alt | **1258** — Chlorophyll concentration decreases with irradiance. | 5 / 0 / 13 · 15/18 | Phytoplankton instead of a core rule (photoacclimation); swap for 5 if the panel's areas should be covered. |

Four of the five are core DEB rules (the category with 36 of the 62 facts);
1239 is hypoxia. If the panel includes phytoplankton experts, use the
alternative.

## For each chosen item, the team agrees

- evidence strength (weak / moderate / strong) and direction (against /
  inconclusive / corroborated);
- optionally, reference labels for the passages that carry the lesson (not
  all 18);
- a short explanation shown to every expert after they answer — which
  passages carry the answer and what an expert should know beyond them.
