# Provenance

This page describes how the catalog and the tools were built. It covers where the programs come from, what was measured on which machines, how a failing run becomes a finding, and what the repository contains.

## Programs

Every program is a small, self-checking, legal device-offload program in C or free-form Fortran. It prints a result line (`RESULT ran_on_host=<0|1> check=<pass|fail>`, or a checksum for fuzz programs). Its expected value is computed in Python or by a spec rule and is never taken from a compiler under test. The sources fall into five groups.

**Generated from the catalog.** `catalog/omp/` and `catalog/acc/` hold the clause grammar, restriction rules and semantic atoms for OpenMP 5.0, 5.2 and 6.0 and OpenACC 3.4, each citing the specification page. The directive skeleton of OpenMP comes from an `llvm-tblgen` dump (`offload/engine/skeleton.py`) with spec overrides. `offload/engine/gen.py` and `gen_templates.py` write one program per atom and one illegal variant per violated rule. `acc_gen.py` does the same for OpenACC, and `c_gen.py` and `acc_c_gen.py` port the programs to C through `f2c.py`. `dataenv_gen.py` writes programs from the data-environment rule table, each with a control that states the attribute explicitly. `widen.py` adds hand-written programs for things real code uses that the grammar does not reach, such as base-language features in device code and pairs of atoms.

**Generated campaigns.** `nested_gen.py` builds nested pointer-linked data structures and uses a Python simulator to compute the expected output. `oop_gen.py` builds families of derived types and object-oriented features. `kbody_gen.py` varies the statements inside one kernel. `fuzz.py` and `fuzz_base.py` write random programs that are legal by construction, and a Python model of sequential execution gives the expected output. `stress.py` writes very large legal programs. A seed and a generator version fix a fuzz program, and `catalog/fuzz_campaigns.yaml` lists the campaigns and their seeds. `mutate.py` audits whether a program's check depends on its atom.

**Public test suites and examples.** `offload/engine/harvest/` converts programs from LLVM `offload/test` and AOMP `test/smoke`. `offload/engine/harvest2/` converts programs from the libgomp testsuite, the OpenMP Examples, AOMP, vendor and training material, and small application kernels. A converter appends a self-check built from the test's own FileCheck lines or from a recorded edit, and each file's header names its repository, commit, path, licence and edits. [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and `data/licenses/` hold the licences and their texts, including the copyleft directories (GPL-3.0 for libgomp, CC-BY-SA-4.0 for one book example). `data/bench/harvest-known/` holds reproducers taken from supercomputing-centre pages, the NVIDIA HPC compilers forum, release notes and application workaround history. `data/bench/wild/` and `data/bench/fresh*/` hold reproducers from public issue trackers, attributed by URL. The notices file marks the licences of `harvest-known/` and `wild/` as not yet reviewed. `data/bench/apps/` pins open-source applications (repository, commit, licence) that are built and run in place. The HeCBench benchmarks are built from a pinned clone, and no HeCBench source is in the tree. The omp_vv and acc_vv suites in `corpus/` serve only as baselines and cross-checks. They are never an oracle or evidence that a program is legal.

**Hand-written findings.** The top level of `data/findings/` holds reproducers written and reduced by hand. The subdirectories hold findings from the campaigns above: `fuzz/`, `nested/`, `oop/`, `stress/`, `malloc/`, `hecbench/`, `harvest/`, `fresh/`, `apps/`, `gcc/`, `catalog/` and `dataenv/`.

**Rules for all sources.** A program counts as legal when `offload/engine/rules.py` accepts it and a front end of another compiler family accepts it. gfortran is used only as a base-language syntax check (`-std=... -fsyntax-only`, never `-fopenmp`) and as an output oracle for the sequential elision. GCC is only ever a compiler under test.

## Machines and compilers

`catalog/machines.yaml` describes three systems, and `catalog/toolchains.yaml` describes the compilers on them. [docs/tooling/toolchains.md](tooling/toolchains.md) is the generated table.

| system | GPU | memory modes | scheduler |
|---|---|---|---|
| AMD MI300A cluster | gfx942 | unified (`HSA_XNACK=1`, the headline mode, with transparent huge pages), copy (`HSA_XNACK=0`) | flux |
| AMD MI250X cluster | gfx90a | copy | flux, interactive queue only |
| shared NVIDIA host, 4 GPUs | A100 80GB PCIe, sm_80 | separate (`-gpu=mem:separate`), managed (`-gpu=mem:managed`) | none; free GPUs only, run under a resource cap |

On the A100 host, `-gpu=mem:unified` builds but aborts at run time, and the machine record quotes the message. That mode is therefore recorded as not applicable.

The compiler releases are AMD AFAR 24.3.0, Cray CCE 19.0.0, 20.0.2, 21.0.3 and 21.0.4, NVHPC 25.11 and 26.9, and GCC 16.2.0 (an AMD build for gfx90a, gfx942 and gfx950 and an NVIDIA build for sm_80). CCE 21.0.4 is used for regression checks against 21.0.3. The MI250X systems carry gfx90a twins of the AFAR and CCE toolchains. Each result row records the node, compile flags, version banner, loaded modules, an environment hash and the git revision (`offload/engine/provenance.py`).

## From a failing run to a finding

1. **Measurement.** `tools/campaigns/run_matrix.py` and the other campaign drivers run every program on every toolchain and memory mode and write result rows. Canary programs with known outcomes (`catalog/canaries.yaml`) run alongside, and a report stops if a canary's result changed.
2. **Reproduction gate** (`offload/engine/gate.py`). Each failing row is rerun in four environments: its original build directory, a differently named build directory, the original path on another node or GPU, and a second run in the original. A failure counts as confirmed only when every valid rerun matches. Otherwise it is `not_reproduced`, `nondeterministic` or `environment`.
3. **Legality.** Before a program is compiled, the pre-run check (`offload/engine/prerun.py`) requires two independent confirmations that it is legal, neither from the compiler under test. One is the project's rules and the other is a front end of another compiler family. For programs that every family rejects, `tools/confirm.py witness` records an independent checker's verdict in `catalog/legality_witness.yaml`. AFAR and upstream LLVM share a front end, so neither counts as confirmation for the other. An expected value is trusted only when two independent sources agree (`offload/engine/expected.py`).
4. **Confirmation** (`offload/engine/confirm/`, [confirm.md](tooling/confirm.md)). A rule table in `catalog/confirm_rules.yaml` assigns each failing cell a verdict, such as `compiler_bug`, `our_bug` or `needs_human`. It also deduplicates cells that share a signature.
5. **Reduction** (`tools/reduce.py`). Delta debugging over statements, clauses, expressions and unused declarations keeps a candidate only if the legality check still accepts it and the failure keeps the same signature on every target. It then writes one-change controls, which are edits of the directives that stay legal and pass.
6. **Drafting** (`tools/new_finding.py`). The header facts are generated from the rows. They are the failing toolchains and modes, the build line, the observed message, the identical-signature count, the gate's four environments, the other families that ran the file correctly, and each control's result. A person writes the title, the specification citation and the argument that the program is legal.
7. **Checks** (`tools/repo/check_findings.py`, `tools/repo/check_citations.py`). Every claim in a header needs a recorded row. Every control needs a passing row on the compilers it is claimed for. The gate must have run in all four environments, and counts and "the same way" must match the rows. Citations must match the page and quoted passage of the specification text. Claims that predate the check are listed in `catalog/findings_claims_baseline.yaml`, which only shrinks.

## Sealed benchmark sets

Some sets are drawn by a fixed rule and sealed, so that a tool can be scored on programs that did not shape it. The rule is part of the set. The harvest holdouts are the programs whose code hash falls in the lowest 30% of the sha256 space (`holdout_by_code`, so two variants of one test land on the same side). HeCBench is split on the parity of the sha256 of a benchmark's directory name. Each sealed set has a `SEAL` file with the hash of its files. Development tools never read sealed programs. The offline lanes do not copy a sealed set off the MI300A system until `catalog/sealed_spent.yaml` lists it. A set is added to that file only after its scores are final, and `fresh`, `fresh2` and `harvest-holdout` are listed. `harvest-holdout` was scored once. `tests/bench/` and `tests/cluster/test_lanes.py` check these exposure rules.

## What is committed

The repository contains the code, `catalog/`, the findings and their controls, the benchmark programs of `data/bench/`, generated tables under `data/reports/` and `data/index/`, vendor check programs and compact check rows under `data/vendor/`, and the site inputs. It does not contain `results/` (raw measurements, the confirmer's batches, the training table, the gate's reruns), `corpus/` (clones of the third-party suites, pinned in [setup.md](tooling/setup.md)) or `spec/` (the specification PDFs, pinned by checksum in the same page). `.gitignore` names all three, and tests that need them skip when they are absent. [regenerate.md](tooling/regenerate.md) lists every generated file with its inputs.

## Authorship

Much of the code, the tests and the documentation was written with AI coding agents (Claude Code) working under the maintainer's direction. The test suite, the committed measurements and the checks in `tools/repo/` hold the work to account, and every finding header must pass those checks. The programs' expected values never come from the compilers under test.
