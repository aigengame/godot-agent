# Current-language refactor record

The owner adopted this pre-1.0 direction on 2026-09-06. Internal revisions may change or be withdrawn. The implementation will converge on one current compositional language and delete obsolete version selection and execution bindings. Implementation proceeds through the tracked issue slices; the overall production refactor remains open.

Start with the [accepted decision](../../badr/0028-current-language-refactor-and-pre-1.0-retirement.md), then the [implementation plan](PLAN.md). The [issue index](ISSUES.md) links the tracking parent #865 and 14 slices with their blockers. Execution-dependency closure #874 is a prerequisite to mandatory deletion #875; closure alone cannot satisfy the parent or final acceptance #879.

| Record | Purpose |
| --- | --- |
| [Plan](PLAN.md) | Background, findings, target boundaries, alternatives, sequence, design gates and rollback |
| [Evidence](EVIDENCE.md) | Six bounded probe families, falsifying cases, provenance and portable reproduction |
| [Core requirements](requirements-matrix.md) · [JSON](requirements-matrix.json) | 109 captured user-story, acceptance and genre routes |
| [Linked delivery requirements](delivery-requirements.md) · [JSON](delivery-requirements.json) | 55 captured acceptance routes on existing delivery issues |
| [Module disposition](module-disposition.md) · [JSON](module-disposition.json) | 143 baseline production files and their intended dispositions |
| [Reconciliation](reconciliation.md) | Superseded clauses, retained rules and implementation owners |
| [Validation](VALIDATION.md) | Documentation delivery checks and evidence limits |
| [Issue index](ISSUES.md) · [JSON](issues.json) | Adopted dependency graph and reused existing owners |
| [Implementation workflow](IMPLEMENTATION.md) | Authorized development branch, per-issue review, integration and delegated decisions |
| [Schema 1 retirement](RETIREMENT.md) | Bounded named-source disposition, removed input path, retained coverage and rollback for #868 |
| [Current capability union](CAPABILITY-UNION.md) | Retained package behavior, deleted release/vector copies, composed public path and rollback for #869 |
| [Namespace expansion](NAMESPACE-EXPAND.md) | Integration boundary, derived namespace view, mandatory transition deletion and handoff for #870–#872 |

GitHub owns live acceptance and task status; bADR-0028 owns the adopted policy; the plan owns delivery sequencing. Matrices preserve exact captured requirement text as provenance. Current issue amendments supersede the identified historical clauses. Evidence is confirmed only within its stated bounds, and no disposable probe establishes full production conformance, genre completion or automatic formal-release/claim activation.
