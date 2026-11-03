# "How this works" — the one screen experts read first

**Status: draft for the project owner's review.** Served with the guidelines
(`HOW_IT_WORKS` in `app/backend/app/services/elicitation_service.py`,
guidelines v2.0) and shown at the top of `/elicitation` on an expert's first
visit, then behind a *How this works* button. Changing it is a change to the
instrument: bump `GUIDELINES_VERSION`, and every later judgment records the
new version.

---

1. You see one stylized fact at a time, with the passages our search found
   for it. Each passage shows where it comes from.
2. Label every passage: does it support the fact, dispute it, or neither?
   Label it by what the passage itself says; if you cannot tell, say so. For
   a passage that supports or disputes the fact, also say what kind of
   evidence it is.
3. Then judge the fact as an expert, from the passages AND from what you
   know: how strong is the evidence, and which way does it point?
4. Say whether your judgment goes beyond or against what the passages show.
   If it does, write a line on why; you can add a reference (DOI) you are
   relying on.
5. Set your confidence and submit. Facts come in a fixed order, so you cannot
   pick them, and you are never given a fact you authored.
6. Other experts judge the same facts independently. You do not see their
   answers, or any machine assessment, while you work.
7. Your judgments measure how far experts agree, and the panel's combined
   verdict is shown next to each fact in the knowledge base. References you
   add go to a curator for review.

---

## Wording on the form itself

| Where | Text |
|---|---|
| Page title | Assess stylized facts — *Judge each fact from the passages shown and from your own knowledge.* |
| Step 1 | **Label each passage.** Does the passage support the fact, dispute it, or neither? Label it by what the passage itself says — most are neutral. If a passage is garbled or outside what you can assess, choose “Cannot judge”. Your own knowledge goes into step 2. Options: Supports / Disputes / Neutral / Cannot judge. |
| Step 2 | **Your judgment of the fact.** From these passages *and* from what you know of the literature. *How strong is the evidence for it?* Weak or sparse / Moderate / Strong. *Which way does it point?* Against / Inconclusive / Corroborated. |
| Step 3 | **Does your judgment go beyond or against what these passages show?** Yes — I relied on something the passages do not contain / No — the passages alone lead me to the same judgment. |
| Reason | *Why? (required)* when Yes, or when the scores go beyond the expert's own labels; otherwise *Note (optional)*. |
| Reference | *Add the reference you are relying on* (open when Yes) / *Add a reference from your own knowledge* (closed otherwise) — goes to a curator, never changes a score. |
| Unresolved source | *Source not yet identified — file Kooy93.pdf (DEB library #2801)* |
| Calibration | **Worked examples.** Before your next fact, work through these examples exactly as you would a real one. The team agreed an answer for each, and you see it as soon as you submit. Examples are not part of the study, and a different answer is not a mistake to hide — it is what the explanation is for. |

Points worth a second look:
- Step 1 asks for labels *by what the passage says* while step 2 invites the
  expert's knowledge. That split keeps passage-level agreement comparable with
  the machine panel (same axes and wording as the agents) while the overall
  judgment is H-EK. If the team prefers experts to label passages with their
  knowledge too, step 1 and the guideline text change together.
- "Inconclusive" replaces the agents' "neutral" for consensus 2 on the expert
  form, to avoid two different meanings of *neutral* on one screen.
