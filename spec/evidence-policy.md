# Evidence policy v0.1

Grades are ordinal labels, not probabilities. They must never be averaged or converted into numeric confidence.

| Grade | Meaning | Examples |
|---|---|---|
| A | Direct, independently reproducible evidence for the exact claim | Executed test with captured output; primary record; official source directly establishing the fact |
| B | Strong source with traceable provenance, but one important limitation | Official documentation for a version not identical to the target; peer-reviewed result with bounded applicability |
| C | Credible but indirect or incomplete support | Reputable secondary reporting; expert analysis with traceable references |
| D | Weak, anecdotal, or materially unverified | Forum assertion, unattributed summary, unsupported model output |
| Unassessed | Provenance or relevance has not yet been reviewed | Newly retrieved item awaiting inspection |

## Independence rules

Evidence is independent only when its underlying origin is independent, not merely because it appears at a different URL. Two articles quoting the same press release are one origin. Two analyses using the same dataset are not independent corroboration. A derived result must identify its parent evidence in `derived_from`.

## Verification protocol

The verifier receives: (1) the exact claim statement, (2) evidence records and source material, and (3) the verification question. It does not receive the explorer's reasoning narrative, chain of thought, or preferred conclusion. Prefer deterministic checks: re-fetch URLs, inspect primary records, run tests, execute code, validate hashes, and reproduce calculations. Model review is a fallback for semantic interpretation, not a substitute for source inspection.

## Arbitration (implemented in `src/neuromesh/arbitration.cr`)

No numeric confidence is computed. Claim status is one of proposed, provisional, supported, disputed, rejected, derived deterministically:

- **Original** evidence has `independence_group = independent_origin` and an empty `derived_from`. Quoted, derived or same-dataset items are never original.
- **Strong** evidence is original, graded A or B, and has `applicability_checked = true` (a reviewer confirmed it applies to the exact claim scope).
- **Superseded** evidence (`superseded_by` names newer, live evidence) is kept for provenance but excluded from arbitration. This is how a later errata or retraction overrides an earlier source.
- `unassessed` evidence is ignored.

Evaluation order for a claim:

1. Any strong contradicting item: `disputed` if any original, non-D supporting item exists; otherwise `rejected`.
2. `supported` if any strong supporting item exists, or at least two C items with checked applicability come from distinct origins (same publisher counts once).
3. `provisional` if there is any supporting evidence that does not meet (2).
4. `proposed` otherwise.

The number of agreeing items or regions never changes status. The Executive may commit the computed status or downgrade along proposed < provisional < supported, never exceed it (`CommitRejected` is logged otherwise).

**Known limit:** arbitration trusts the grade, `independence_group`, `derived_from` and `applicability_checked` labels it is given. The harness verifies that excerpts are verbatim quotes, not that the labels are right.
