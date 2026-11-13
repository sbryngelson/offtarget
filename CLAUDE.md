# Working on this repository

A catalog of legal OpenMP and OpenACC device-offload programs (C and Fortran) that a compiler gets wrong, the `offload` command that looks them up (`can-use`, `issues`), and the public site built from the findings. Only device offload is in scope ([docs/scope.md](docs/scope.md)).

Read first: [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), [docs/README.md](docs/README.md) (reading order) and [docs/tooling/contributing.md](docs/tooling/contributing.md) (layout, standing rules, runbooks). Every directory has a README that says what is in it.

## Rules that tests enforce

The full list, with the test for each, is in "Standing rules" of docs/tooling/contributing.md. The ones that matter most:

- A program counts as legal only if the project's rules and a front end of another compiler family say so, never because the compiler under test accepts it. gfortran and `gcc -fopenmp` are never evidence that a program is legal. The omp_vv suite is never an oracle.
- A finding needs the reproduction gate and recorded rows (the stored result lines of each run). The header facts are generated from the rows and checked against them. Do not write a count or a verdict by hand.
- Sealed benchmark sets (`data/bench/*/SEAL`, `catalog/sealed_spent.yaml`) are never read, edited or used to tune anything.
- The tooling never posts or reports anything externally. Vendor report drafts are never published.
- No AI attribution lines in commit messages. No first person in site copy. Docs say what the tool does, tersely; no work-item or process vocabulary (`tests/test_repository.py` checks).
- Do not push, merge or publish unless asked.

## Commands

    python3 -I -m pytest -q -n auto -m "not gpu"   # the tests; needs pytest-xdist (tools/repo/test_requirements.txt)
    python3 -I tools/repo/check_findings.py   # findings against their recorded rows
    python3 -I tools/regenerate.py --check    # every generated file is current

The tool itself runs as `python3 -m offload` from the root: `-I` drops the checkout from the import path.

Do not trim tests to make the suite faster. Share or cache the expensive setup instead. A fresh clone has no `results/`, `corpus/` or `spec/`. Tests that need them skip and say so ([docs/tooling/setup.md](docs/tooling/setup.md)).

## Machines and compilers

The catalogs do not say where a compiler is installed or how to reach a machine. That differs per user. Copy `catalog/local.example.yaml` to `catalog/local.yaml` (git-ignored) or `~/.config/offload/local.yaml`. The tests read a made-up user's settings (`tests/data/local_settings.yaml`); put your own file in `OFFLOAD_TEST_LOCAL` for the tests that run a real compiler. Do not run compilers or tests that need a GPU on a login node. Use the machine's scheduler.

## After a change

- Editing the confirmer (`offload/engine/confirm/`), the rules, claims, rulings or findings makes the committed confirmer batches stale, and `tools/regenerate.py --check` reports it. To rerun them, run `tools/jobs/run_regen_confirm.sh` and `tools/jobs/run_widen_confirm.sh` on a compute node ([docs/tooling/regenerate.md](docs/tooling/regenerate.md)).
- Moving or renaming a test file changes paths that catalog entries and the Tioga class map (`tools/lanes/tioga_suite.py`) name. The tests that read them fail until both are updated.
- For a new compiler, release, GPU or memory mode, follow the checklist in "Add a compiler or a compiler release" and "Add a GPU architecture or a memory mode" of docs/tooling/contributing.md. `test_adding_a_compiler_is_a_config_edit` in `tests/cluster/test_reports.py` runs the catalog steps on a copy with two fake releases and is the worked example.
