# SDD ledger — plan: docs/superpowers/plans/2026-08-21-stm32-v11-v2-v3-evolution.md

## Preflight rulings

- Ruling: no Git worktree or commits — the approved product boundary forbids Git initialization; use assigned file ownership, tests, reports and final whole-workspace review instead. Cost if wrong: less convenient diff packaging, mitigated by isolated ownership and a final read-only audit.
- Ruling: independent implementation agents may run in parallel — the approved plan explicitly requires model-specialized parallel work and assigns non-overlapping files. Cost if wrong: integration conflicts, mitigated by main-agent ownership of shared entrypoints and no worker edits to `Student_Profile/`.
- Ruling: replace obsolete P001–P004 test fixtures with real catalog IDs instead of adding a production legacy bypass — the authoritative learner ledger contains no such historical project events. Cost if wrong: an external caller using undocumented fake IDs must migrate to stable catalog IDs; benefit is a closed V1 project gate.

## Interface scan

| Tasks | Producer / consumer | Finding |
|---|---|---|
| V1/router → integration | `IntentDecision` and public routing rules | Main agent owns final `SKILL.md`; worker owns executable router only. |
| V2 engine → experience library | schemas, stage names, project pattern contract | Engine owns schemas/scripts; library owns reference content and content validators. |
| V2 → V3 | immutable project/evidence refs | No cross-store write; V3 records references only. |
| V1/V2/V3 → integration | independent tests and references | Main agent runs combined tests before changing entrypoint metadata. |

## Baseline

- 2026-08-21: `state_tool.py validate` succeeded at revision 1.
- 2026-08-21: `python -m pytest -q` — 39 passed.

## Task progress

- Task 5 integration RED: `tests/test_skill_evolution.py` failed 3/3 because the executable router, three new read-only agents, and enabled sidecar contract did not exist.
- Task 5 partial GREEN: specialist agent configuration and enabled/isolated sidecar contract now pass 3 focused tests; router/reference link remains dependent on Tasks 1, 2 and 4.
- Task 1 fix round 1: manual route probe caught “我要做一辆智能车”→V1 and a bare competition implementation question→V3; 7 new RED variants were added and the corrected router passed 8/8 focused cases, 36 V1 tests total.
- Task 3 review: Spec failed — catalog records repeated mismatched scenarios, all 30 normalized pattern bodies were identical, and the frozen 15 new IDs/titles were not honored. Fix round 1 dispatched with semantic fixtures and project-specific content requirements.
- Task 4 review: Spec failed — complete drafts lacked student-decision/raw-evidence/contribution gates, RuleSet edition was not bound to intake, idempotency conflicts and future timestamps were accepted, and schemas were weak. Fix round 1 dispatched with executable reproductions.
- Task 2 V1.1 final review: Spec passed and quality approved after four adversarial rounds. The live-write guard now blocks unknown legacy active courses without materializing recovery files; accepted cancellation, idempotent replay and ledger-first recovery remain deterministic. State suites reached 54 passing tests, and all six real `Student_Profile` files remained byte-for-byte unchanged during validation.
- Task 4 V3 final review: Spec passed and quality approved after three adversarial rounds. Rules are bound to competition/edition/track, stale or unavailable official rules fail closed, full drafts require student decisions and raw evidence, tool-authored claims cannot impersonate measurements, and submission remains user-reported with receipt evidence.
- Task 3 V2 engine fix rounds: adversarial probes exposed permissive safety text matching, weak target/toolchain parsing, false V5 evidence, incomplete resource checks and invalid rollback/observation acceptance. The final implementation replaces these with structured gates, a conservative F103C8/LQFP48 capability map, evidence-kind/source compatibility and baseline-bound rollback. Implementer reported 70 focused tests and 33 exact mutation probes passing; independent final review is pending.
- Task 3 V2 experience fix rounds: a fresh rescue implementation replaced repeated prose templates with a single schema-v3 manifest and deterministic renderer. Thirty detailed patterns now model typed endpoints, AF/SWD constraints, split supply rails and project-specific resource ranges. Final fixes added port-to-rail voltage closure, concurrent consumer peak budgets and source-capacity closure; implementer reported 39 content tests and renderer drift checks passing; independent final review is pending.

## Review-round rulings

- Ruling: safety, evidence provenance, state recovery and electrical budget findings are load-bearing and must be fixed before release, regardless of existing green tests. Cost if wrong: additional implementation rounds and stricter fail-closed behavior; benefit is preventing confident but unsafe guidance.
- Ruling: the F103C8/LQFP48 capability tables intentionally reject unlisted remaps instead of guessing. Cost if wrong: a valid advanced remap may require a future explicit table update; benefit is that V2 never invents pin, DMA or IRQ compatibility.
- Ruling: competition adapter URLs and archived cases are discovery metadata, not frozen rules. Cost if wrong: the first V3 exchange may pause for official-source retrieval; benefit is avoiding stale eligibility and deadline claims.
- Task 3 V2 experience final breaker: the first Round 5 review rejected overlap-only voltage validation. The main agent added RED mutations for a 4.75–12 V HC-SR04 domain and an over-wide terminal requirement, then changed the invariant to `required range ⊆ component-port range` and `domain range ⊆ required range`. `innovation-076/078` light-sensor rails were narrowed to their common 3.0–3.3 V safe range. Independent Round 6 review passed the spec and approved quality.
- Task 3 V2 engine final breaker: an independent reviewer found plain Chinese `接` could bypass direct Echo/GPIO and GPIO/motor checks even when contradictory structured safety metadata was present. Two exact tests failed first; the fix now detects endpoint relations per text field while allowing explicit `分压/电平转换` and `driver/TB6612` bridge paths. Independent replay approved both unsafe rejection and safe bridge acceptance; the V2 engine suite reached 72 passing tests.
- Final blind review: a GPT-5.5 red-team agent ran 55 paraphrase probes across routing, readiness, catalog gates, Blue Pill identity, Echo/motor safety, evidence levels, baseline invalidation, competition freshness/compliance and cross-store isolation. It reported Spec passed, quality approved, no Critical or Important findings. No real hardware, flashing or live official-site retrieval was claimed.
