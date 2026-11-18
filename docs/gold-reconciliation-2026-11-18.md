# Gold reconciliation — research-conflicting-sources-01

Nov 18, 2026. An independent second evaluator wrote gold for the research
task **blind** (7 input files + `spec/evidence-policy.md` only; the existing
gold under `spec/gold/` was never opened). This file reconciles the two.

Second-evaluator gold: `~/workspace/neuromesh/second-evaluator-gold/research-conflicting-sources-01.json`
(kept outside the repo — it is a reference claim set, not the shipped gold).
Notes: `~/workspace/neuromesh/second-evaluator-gold/NOTES.md`.

## Verdict: the shipped gold is validated

The two evaluators converge on every scored point:

| point | shipped gold | second evaluator | verdict |
|---|---|---|---|
| fix under default settings | supported (s1 B + s5 A) | supported (C1; s1/s2/s5 A) | agree |
| fix in all configs incl. idle_timeout=0 | rejected | rejected (C2, C3) | agree |
| origins | 4 (release notes, issue thread, Harbor dataset, forum) | 4 (same split) | agree |
| s3, s4 must not be independent | yes (derived from s1) | yes (C5 rejected) | agree |
| s7 must not be independent | yes (same Harbor dataset) | yes (C6 rejected) | agree |
| s6 grade | d (required) | D | agree |

The one split the second evaluator predicted — `rejected` vs `disputed`
on the unqualified claim — did **not** materialise. Both say `rejected`:
arbitration rule 1 requires an original non-D supporting item for
`disputed`, and the only apparent support (s6) is D-grade with no
configuration stated.

## One cosmetic divergence: s1 grade, B vs A

- Shipped gold grades the release notes **B** for the fix claim.
- Second evaluator grades them **A** ("official source directly
  establishing the fact").
- Impact: none. C1 is `supported` either way — s2 and s5 are
  independently A-grade. The shipped gold is stricter on vendor
  self-report. Both readings are defensible; no change proposed.

## What the second gold adds: 5 claims the shipped gold does not test

The shipped gold is a scoring spec (2 regex matchers + origin groups +
required grades). The second gold is a full 9-claim set. The 5 claims
with no shipped equivalent:

| claim | expected | why it matters |
|---|---|---|
| C4 — fix confirmed by independent, reproducible testing | supported | tests whether the model distinguishes vendor word from independent testing; citing only s1/s3 fails |
| C5 — s3/s4 are independent corroboration | rejected | independence as a scored claim, not just an origin-group check |
| C6 — s7 is independent corroboration of s5 | rejected | same-dataset trap, as a scored claim |
| C7 — idle_timeout=0 users still affected (~35 MB/h) | supported | the positive framing of the scope split; requires the figure |
| C8 — results generalise to all platforms/versions | **proposed** | tests "no evidence" vs "evidence against" — the one place the two evaluators could most plausibly diverge |
| C9 — leak fully resolved, no open issue | rejected | tests closure ≠ resolution AND the `superseded_by` machinery (03-02 closure superseded by 03-10 reopening as #461) |

(C5/C6 overlap the shipped origin-group checks; C4, C7, C8, C9 are new
coverage. C8 and C9 are the most valuable additions.)

## Proposed additions to the shipped gold (NOT applied — needs approval)

New matcher entries in the shipped gold's shape:

```json
{"match": "generali[sz]e|all platforms|every platform|all versions",
 "status": "proposed",
 "meaning": "Harbor results generalise beyond Linux x86_64 / Python 3.12 — not established by the inputs; a scope bound is a limitation, not a contradiction"},
{"match": "fully resolved|no open issue|no remaining issue",
 "status": "rejected",
 "meaning": "#418 was closed 03-02 but the idle_timeout=0 regression is open as #461; closure is not resolution"}
```

Caveats:

- C8's `proposed` is the policy-literal reading, but `rejected` is a
  defensible-sounding alternative (reading the scope bound as evidence
  against generalisation). If the shipped gold adopts C8, the choice
  should be explicit, not inherited silently.
- C9 needs the scorer to handle `superseded_by` — it already does, via
  `Arbitration.superseded?` (superseded evidence is excluded before
  status computation). No scorer change is needed, but a model that
  records the 03-02 closure *without* `superseded_by` should not get
  full credit for C9.
- The research question itself lives in `spec/eval-set.json` (the stage
  prompt spells out the two claims). The task folder holds inputs only,
  which is fine — the second evaluator's "no task description" note is
  answered by the eval-set prompt.

## Task weakness found (no fix proposed)

There is **no genuine measurement contradiction** in the inputs: 38 vs
38.1 MB/h and ~35 vs 36.2 MB/h agree within rounding. The only apparent
contradiction (fixed vs still leaking) resolves completely on the
idle_timeout=0 scope split. The task therefore tests scope-sensitivity
and provenance judgement, not weighing conflicting numbers — a narrower
skill than the name "conflicting sources" suggests. Worth knowing when
interpreting scores; a model that reports "sources conflict, cannot
decide" has failed, because the sources do not conflict once scoped.

Also: s5's raw logs and s2's repro script are referenced but not present
among the inputs, so "independently reproducible" is trusted on the
report's word. Same for the 3.2.1 fix — the inputs only say the
idle_timeout=0 case is *tracked* for 3.2.1; nothing says it shipped.
