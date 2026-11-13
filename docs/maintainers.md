# Maintainers

The two commands need nothing from `tools/`. Run its scripts with `python3 -I` from a checkout, for example
`python3 -I tools/regenerate.py --list`. Measurements need the compilers and GPUs (Tuolumne, Tioga and a machine with
an A100). The tests and the website do not.

## Layout

| path | holds |
|---|---|
| `offload/` | the command line: `can-use`, `issues`, and the data bundle |
| `offload/engine/` | the engine: catalog, confirmer, generators, harness, site build |
| `tools/` | maintainer scripts; the top level has `campaign.py`, `confirm.py`, `new_finding.py`, `reduce.py`, `regenerate.py`, `site_publish.sh` |
| `tools/campaigns/`, `tools/dataenv/`, `tools/wild/` | campaign runners, data-environment tools, wild-code benchmark tools |
| `tools/derive/`, `tools/site/` | derived artifacts and claims, site and dashboard builders |
| `tools/jobs/`, `tools/lanes/` | job scripts for the machines, the wingtip and Tioga test lanes |
| `data/evidence/`, `tools/repo/` | probe programs, repository checks (findings, citations, docstrings, bundle manifest) |
| `data/` | everything that is evidence or input: the folders below ([data/README.md](../data/README.md)) |
| `data/findings/` | the findings; `index.yaml` is their index |
| `data/index/` | corpus and directive coverage indexes, claims, seeds |
| `data/reports/` | generated support tables, campaign reports and run logs |
| `data/vendor/` | per-vendor report drafts (`amd`, `hpe`, `nvidia`) and the check programs behind them |
| `data/bench/` | benchmark sets and their sealed hold-outs |
| `data/licenses/` | licence texts of third-party sources |
| `catalog/` | rules, models, toolchains, machines, machine-readable inputs |
| `site/` | templates, static files and committed inputs (`inputs/`) of the website |
| `tests/` | the test suite ([tests/README.md](../tests/README.md)) |
| `docs/` | the documentation ([README](README.md)); `upstream.md` lists problems found in upstream test suites |
| `corpus/`, `results/`, `spec/` | third-party sources, measurements and spec PDFs; links, not in the repository |

Sealed benchmark sets (`data/bench/*-holdout/`, `catalog/sealed_spent.yaml`) are never read before scoring, and tests check this.

## Add a finding

1. Reduce a failing program with `tools/reduce.py --program FILE --target cce21/1 --name NAME --out DIR`.
2. Draft the finding with `tools/new_finding.py DIR/NAME.f90 --campaign NAME --rows DIR/rows.jsonl --control DIR/controls/*`.
   Add `--write` to put the file and its index entries in place. The title and the argument that the program is
   legal stay `TODO(human)`.
3. Fill those in. `tools/repo/check_findings.py` fails until you do.
4. Regenerate (below) and run the tests.

`data/findings/AUTHORING.md` describes the format and the rules.

## Regenerate

```
python3 -I tools/regenerate.py --list
python3 -I tools/regenerate.py --check
python3 -I tools/regenerate.py --offline
```

`--check` reports every committed generated file that is out of date and writes nothing. `--offline` rebuilds the
files that need only `results/`. The confirmer batches need a compute node. Run `tools/jobs/run_regen_confirm.sh`
and `tools/jobs/run_widen_confirm.sh` there, with `INSTALL=1` in the environment.

## Test

```
python3 -I -m pytest -q
```

Tests that need `results/`, `corpus/` or `spec/` skip and name what is missing. `tools/lanes/wingtip_offline.sh tests`
runs the whole suite on the A100 machine. `tools/lanes/run_tioga_suite.sh` runs the part that needs Tioga.

## Publish the website

```
tools/site_publish.sh OUT_DIR
```

builds the pages from the committed findings and tables and checks them. It stops if it finds a user name, host name
or private path in the output. A GitHub workflow publishes the same output when site publishing is switched on in the
repository.

## Reference

These pages describe each part of the tooling and the commands to run it.

| page | covers |
|---|---|
| [setup](tooling/setup.md) | the inputs a clone needs (spec PDFs, corpus, results) and how to get them |
| [contributing](tooling/contributing.md) | the standing rules, and the runbooks for adding a finding, a compiler or a campaign |
| [regenerate](tooling/regenerate.md) | every generated file, its inputs, the command that rebuilds it and its currency check |
| [confirm](tooling/confirm.md) | the confirmer: ingesting failures, the legality gate, drafting findings |
| [expected-behaviour](tooling/expected-behaviour.md) | how expected values are derived and checked |
| [nested-data](tooling/nested-data.md) | the nested pointer and aggregate program generator |
| [site](tooling/site.md), [publishing](tooling/publishing.md) | building, checking and publishing the website |
| [dashboard-publish](tooling/dashboard-publish.md) | publishing the dashboard data |
| [wingtip](tooling/wingtip.md) | the A100 lane and the Tioga test lane |
| [toolchains](tooling/toolchains.md) | the compiler releases measured (generated from `catalog/toolchains.yaml`) |
| [omp5-vs-52](tooling/omp5-vs-52.md), [omp-50-vs-52-results](tooling/omp-50-vs-52-results.md) | the OpenMP 5.0 against 5.2 comparison (generated) |
