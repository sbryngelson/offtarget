# offload/engine/confirm

The bug confirmer. It takes a failing cell of the catalog or a fuzz program, gathers evidence, and applies versioned rules to decide whether the compiler is at fault. For a confirmed bug it minimizes the program, looks for a duplicate finding and drafts a finding. `docs/tooling/confirm.md` describes the design and formats.

The entry point is `tools/confirm.py`, with subcommands `case`, `batch`, `validate`, `regress`, `promote`, `backlog` and `triage`. In code, `engine.confirm(case)` returns the verdict as JSON.

It reads stored results under `results/` (`ingest.py`), `catalog/confirm_rules.yaml`, `rulings.yaml`, `machines.yaml` and the findings index. It writes `evidence.jsonl` (append only), drafts and regression output under `results/confirm/`.

- Cases and evidence: `model.py` data types; `ingest.py` cases from stored results; `store.py` evidence store; `collectors.py` evidence collectors; `facts.py` facts the rules read; `execute.py`, `jobs.py`, `machines.py` running and scheduling.
- Verdict: `rules.py` rule engine; `engine.py` per-case pipeline; `legality.py`, `witness.py` legality gate and independent witnesses; `forms.py` later forms of constructs; `registry.py`, `ports.py` rulings and C/Fortran equivalence.
- Actions: `minimize.py` reducer; `findings.py` duplicate lookup; `draft.py` drafts and promotion; `backlog.py` bugs without a finding; `programs.py` program kinds.
- Vendor claims: `claims.py` claim format; `triage.py` mismatches run through the rules.
- Checks: `validate.py` against hand verdicts; `regress.py` a new compiler against an old one; `decisions.py` agent decisions and spot checks.

Read `engine.py` first.
