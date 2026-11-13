# offload/engine

The machinery behind the catalog. It generates test programs, runs them on compilers, decides which failures are real compiler bugs, and builds the public data. Modules are imported as `offload.engine.NAME`. The drivers that run them are in `tools/` and `tools/campaigns/`, and design notes are in `docs/tooling/`.

Sub-packages, each with its own README.md:

- `confirm/` is the bug confirmer.
- `site/` builds the public site data.
- `harvest/`, `harvest2/` and `harvest_known/` take programs and bug reports from outside sources.
- `campaigns/` holds the campaigns that use the common interface.

## Catalog, rules and spec
`catalog.py` atoms and slice; `grammar.py` directive parser; `rules.py` restriction rules and `ProgramTree`; `acc_rules.py`, `c_rules.py`, `dataenv_rules.py` rule predicates and tables; `spec_text.py` sectioned spec text; `coverage.py` restriction-sentence inventory; `citations.py` spec citation check; `toolchains.py` compiler registry.

## Generators of catalog programs
`gen.py`, `gen_templates.py` Fortran OpenMP programs per atom, legal and illegal; `acc_gen.py` OpenACC 3.4; `c_gen.py`, `acc_c_gen.py` C ports via `f2c.py`; `dataenv_gen.py` data-environment rule programs; `combos.py` directive orderings; `widen.py`, `widen_progs.py` hand-written programs near real code; `nested_gen.py`, `nested_emit.py` nested pointer data; `oop_gen.py` derived-type families; `kbody_gen.py`, `kbody_emit.py` kernel-body variations; `hecbench*.py` HeCBench builds; `apps.py` application corpus; `skeleton.py` catalog from a tblgen dump.

## Fuzzers, stress and reducers
`fuzz.py`, `fuzz_base.py` random legal Fortran programs; `fuzz_steer.py`, `fuzz_profile.py`, `usage.py`, `idioms.py` steering from real code; `fuzz_exec.py`, `fuzz_campaign.py`, `fuzz_report.py` run and triage; `stress.py`, `stress_c.py`, `stress_exec.py`, `stress_report.py` very large legal programs; `fuzz_min.py`, `stress_min.py`, `malloc_dd.py`, `reduce.py` delta debugging; `mutate.py`, `transforms.py` mutants and equivalent rewrites.

## Running and checking programs
`harness.py` build, run and classify one program; `run_matrix.py` the matrix; `prerun.py` legality and race check; `offload_scope.py` device-only scope; `expected.py` trusted expected results; `flang_oracle.py`, `clang_oracle.py` frontend cross-checks; `canary.py` known-outcome controls; `devtemps.py` device-heap detector; `provenance.py` row metadata; `baseline.py`, `corpus_check.py`, `ompvv.py` corpus runs and readers.

## Campaign interface and reproduction gate
`campaign.py` the common steps from generation to report; `gate.py`, `gate_run.py`, `gate_stored.py`, `gate_report.py` rerun a failure in separate environments before it counts (the reproduction gate).

## Result reports and findings
`report.py` support table and vendor-claim comparison; `fuzz_report.py`, `stress_report.py`, `hecbench_report.py`; `finding_header.py`, `finding_rows.py`, `finding_claims.py` finding file headers and the rows that back them.

## Shared helpers
`root.py` data location; `fsource.py` Fortran source model; `c_program.py` C program tree; `hdrwrap.py`, `textclean.py` text rules; `nested_cites.py`, `kbody_cites.py` spec citations per campaign.
