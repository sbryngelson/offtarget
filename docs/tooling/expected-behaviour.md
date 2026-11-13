# Expected behaviour from independent sources

A wrong answer is a finding only if the expected answer is right. The expected value of a fuzz program comes from the fuzzer's Python model (`offload.engine.fuzz`). The expected value of a catalog program comes from its own oracle, the reference values the generator wrote into it. This page describes how an expected value becomes trusted: two independent sources must agree on it.

| Part | Location |
|---|---|
| Sources, tags, agreement rule, elision analysis, builds, toolchain runs | `offload/engine/expected.py` |
| Metamorphic rewrites and the presence probe | `offload/engine/transforms.py` |
| Small Fortran source model used by both | `offload/engine/fsource.py` |
| Command line and report | `tools/derive/expected.py` |
| Tests | `tests/engine/test_findings_afar.py` |
| Stored results (git-ignored) | `results/expected/` |
| Generated report | [data/reports/expected-sources.md](../review/expected-sources.md) |

## Sources and tags

Every source produces an `Evidence` with one tag, a status (`value`, `inapplicable`, `no_value`, `conflict`), the value when there is one, and the observations behind it. Values are compared as strings: `checksum=<n>` for a fuzz program, `check=pass|fail` for a catalog program, `error_termination` for a run that ends with the toolchain's runtime error message (`offload.engine.harness.ERROR_TERMINATION`). The `ran_on_host` field is never compared.

| Tag | Meaning |
|---|---|
| `elision` | Sequential elision. The directives are comments to a compiler without OpenMP. The program is built by plain `gfortran` and by AFAR `amdflang`, both without `-fopenmp`, against a sequential `omp_lib` (`ELISION_OMP_LIB`, which has one initial thread on the host, one team and no devices), and run on the host. The source has a value when both builds print the same one. Different values are a `conflict`. A value from one build only is `no_value`. It applies only where the rule in "When elision applies" holds. |
| `metamorphic` | Spec-equivalent rewrites (next section) run on the toolchains together with the original. A toolchain with at least two results (original and rewrites) that all coincide is a stable witness. The source's value is the stable witnesses' common value (`conflict` if they differ). A toolchain whose results differ across the rewrites violates the metamorphic relation: it is wrong on at least one of them, and that is recorded. |
| `model` | The fuzzer's Python model, or a catalog program's own oracle (`check=pass`, or `error_termination` for a negative probe). The fuzz model counts only together with `elision` or `metamorphic`, never with `probe` alone. A catalog oracle is the claim under test (always `check=pass` for a result program), so it counts only together with `elision` or `derivation` (`CATALOG_MODEL_PARTNERS`). A disagreement with elision is reported as a suspected model bug. |
| `probe` | The presence probe (`offload.engine.transforms.presence_probe`): the program with self-checks of the device data environment. A calibration maps an array with `target enter data` (it must be present) and removes it with `target exit data ... delete` (it must be absent), so a runtime whose `omp_target_is_present` always gives the same answer cannot pass. At every host point around a data or target construct (except between a `nowait` construct and the next `taskwait`), each mapped variable's `omp_target_is_present` is compared with the presence the reference-count rules fix (OpenMP 5.2 §5.8.3, §13.6-13.8; the walk is `offload.engine.expected.presence_snapshots`). The program prints `PROBE presence=pass|fail` before its result line and before any construct with a `present` modifier. A toolchain on which every assertion held and that ran on the device (or ended in error termination) is a state-verified witness. The source's value is the value such witnesses print. |
| `consensus_only` | The toolchains' own results on the original agree. A hint and never validation, because CCE 19, 20 and 21 share bugs. |
| `derivation` | The expected value derived by hand from the spec text. It is written in the catalog program's header as `! derivation (<value>): <text>`, with the section and page of the program's version (`catalog/omp/derivations.yaml`; `offload.engine.gen.with_derivation` adds the line to the legal programs `generate` returns, outside the audited body). No toolchain and not the generator's check code computes it. Programs whose expected value the spec does not fix (it depends on the memory mode or on an implementation-defined resource) have none. |

## The agreement rule

`offload.engine.expected.decide` returns one of these verdicts.

| Verdict | Condition |
|---|---|
| trusted | Two independent sources (`elision`, `metamorphic`, `model`, `probe`, `derivation`) give the same value and no independent source gives another. The fuzz `model` counts only with `elision` or `metamorphic`; a catalog `model` only with `elision` or `derivation`. `metamorphic` and `probe` are both values printed by toolchains: when one compiler family backs both (`offload.engine.toolchains.family`; CCE 19, 20 and 21 are one family), they count as one source. |
| disputed | Independent sources give different values. All are recorded, and a majority vote does not resolve them. |
| provisional | Fewer than two independent values. |
| derived | Two sources agree but nothing executed shows the value: no device run printed it (withdrawn runs excluded), elision does not apply, and neither the program nor its C port ran correct on the device on any compiler, memory mode or GPU (`results/matrix*.jsonl`). Typically the program's own oracle plus a hand derivation. |
| implementation_defined | The triage found that the quoted spec sentence leaves the behaviour open. It is not a support verdict. |

A catalog verdict is trusted only with an executed witness. For a copy-dependent program (`copy_independent` false) the witness must come from the verdict's memory mode (copy mode: `HSA_XNACK=0` rows, MI300A X0 and gfx90a). A compiler withdrawn by the triage is no witness for the catalog (Fortran) program. Its C port, built by another front end, still can be.

A source whose status is `conflict` (its own witnesses disagree, for example two stable metamorphic witnesses with different values) gives no value. It neither counts nor blocks a verdict from the other sources. Its detail is in the report.

### Triage

A disputed verdict gets a written disposition in `catalog/expected_triage.yaml` (summary in [data/reports/triage-2026-10.md](../review/triage-2026-10.md)):

| Disposition | Effect |
|---|---|
| `program_fixed` | The program was fixed, rerun and re-audited. |
| `oracle_fixed` | The oracle was fixed, rerun and re-audited. |
| `compiler_wrong` | A finding with a minimal reproducer shows the listed compilers' value wrong. Their runs, in every memory mode and on both GPUs, are withdrawn as metamorphic and probe witnesses before the rule is applied. |
| `implementation_defined` | The verdict is `implementation_defined`. |

The name `implementation_defined` also appears as the no-oracle evidence label of a program's check (the "implementation-defined" cells of the support tables). The two are unrelated.

### Memory modes

Verdicts are per memory mode. Every run behind one verdict has the same `HSA_XNACK` (`assess` refuses a mix). A program may depend on separate copies (map `self`, `present`, the `copy_mode_only` programs), so a copy-mode run is no spec-equivalent rewrite of a zero-copy run.

### Relation to the mutation audit

The verdict sits next to the mutation-audit disposition (`offload.engine.mutate.DISPOSITIONS`) and never changes it (`disposition_note`). The audit asks whether a program's check depends on the atom. The verdict asks whether the expected value is right. A trusted value does not make an unaudited oracle valid, and an audited `valid` oracle stays valid when its value is provisional.

## When elision applies

The rule is `offload.engine.expected.ELISION_RULE`, and `elision_applicability` checks it. The method assumes a race-free program with deterministic reductions. The fuzzer guarantees this by construction and the catalog programs are written to meet it. The conditions below are checked.

1. No floating-point reduction or atomic update (reduction order).
2. No runtime routine whose value can reach the result.
   - Allowed: the host flag idiom `x = merge(1, 0, omp_is_initial_device())` (x only feeds the `ran_on_host` field), `x = omp_get_default_device()` used only in device clauses, and the guards `if (omp_get_thread_num() == 0)` and `if (omp_get_team_num() == 0)` where the guarded code runs exactly once in OpenMP execution. That means no loop construct between a thread guard and its parallel region, a team guard inside every enclosing teams region, or a team guard directly in a teams region. `single` and `masked` (filter 0) obey the same once-only condition.
   - No write to shared or reduction storage runs once per team or thread (`redundant_execution`). The write is flagged when it sits directly in a `teams` or `parallel` region with no worksharing construct (`do`, `distribute`, `workdistribute`, `loop` by its binding), `single`, `masked`, `sections` or once-only guard between it and the region, and no private copy of the variable there. Sequential execution runs such a write once, OpenMP once per team or thread.
   - The check does not read `num_teams(1)`, `num_threads(1)` or `if(.false.)` on the region. It does not recognise a guard through a variable (`tm = omp_get_team_num()`), but the runtime-routine rule already excludes such programs.
3. No device-only semantics: no `present` modifier, no declare target or module variable, no device pointers or addresses, no `device(ancestor)`, mapper, iterator or `requires`. The result must also not depend on the device data environment. A version analysis runs the program with separate host and device copies of every variable. It models map entry and exit with reference counts and `always`, `target update`, the firstprivate, private, lastprivate and reduction copies, the implicit data-sharing and mapping rules of 5.2 §5.8.1 and §5.1.1, and the combined-construct rules of §17.2 (for example the implied `map(tofrom)` of a lastprivate or reduction item on a combined target construct). It checks that every read sees the copy sequential execution would see. It runs twice, once with the reference-count rules and once with every map copying unconditionally, so the result depends neither on copies nor on reference counts. A partial or conditional write keeps the previous version as a component, so two copies agree after it only if they agreed before. A lastprivate item assigned only in some iterations without the `conditional` modifier is caught that way.
4. No construct whose sequential execution is not one of its conforming executions or whose effect is not on values: `linear`, scan/`inscan`, ordered `depend`/`doacross`, user-defined reductions, `declare mapper`, `declare variant`, `metadirective`, `dispatch`, `interop`, `threadprivate`, `copyin`, `cancel`, `error`, `detach`, `default(private|firstprivate)`, `masked` with a nonzero filter, conditional compilation (`!$`) lines.
5. Base language. The version analysis tracks storage, not names.
   - A structure is tracked component by component (`dr%a`, `dr%nd%k`, `ds%u` for an array of structures). The parts of a structure mapped on one construct are one storage block whose reference count is the structure's. A part that is not on the device may not be mapped while other parts are present (5.2 §5.8.3 leaves that case open). A referenced element of a structure with mapped elements must itself be mapped (§13.8). A structure referenced without any clause is mapped whole (aggregate category), without its pointer components, whose association status is then undefined (§5.8.3).
   - `p => t` makes the pointer p an alias of the TARGET variable t. A pointer referenced in a target region must be a map list item of that construct whose pointer or target is created there (it is attached). An allocatable scalar or a pointer referenced in a target region needs an explicit clause.
   - A call of an internal subroutine runs its body on the actual arguments, which are whole variables: argument association shares their storage (5.2 §5.1.1, for a scalar, a structure, or an array that is not a pointer or assumed-shape array). A pointer actual of a non-pointer dummy may be passed as a copy, so it may not be present on the device at the call, nor be referenced in the body by another name. VALUE dummies are copies. An explicit-shape dummy must match the actual's extents (checked against its ALLOCATE). An absent optional dummy is ignored in a clause and may not be referenced (§3.2.1). The locals get names of their own.
   - An array section in a map or `target update` clause copies only its part, so a later read of the rest counts as a dependence. Exceptions: `:` or `1:extent` in every dimension, and an update of the section that a host loop (`do i = lo, hi, step` writing `x(i)`) wrote since the copies last agreed.

The data-environment half of the rule (rule 3 without rules 1, 2 and 4) is `copy_independent`. It is the precondition of the host-execution rewrite `if_false`.

## The metamorphic rewrites

`offload.engine.transforms.TRANSFORMS`. Every variant must also pass the legality checks, or it is not run. A fuzz variant is checked by `offload.engine.fuzz.check` (rules, gfortran, AFAR flang's frontend). A catalog variant is checked by the rules at its version and gfortran at its std level.

| name | rewrite | precondition |
|---|---|---|
| `if_false` | `if(.false.)` on target data / enter / exit / update, `if(target: .false.)` on target constructs: the regions run on the host in the host data environment (5.2 §13.8) | `copy_independent`; no write runs once per team or thread (`redundant_execution`: the host picks its own number of teams and threads); no `if` clause on a target directive |
| `split_combined` | `target X` becomes `target` + `X`, with clauses distributed by 5.2 §17.2: map, device, defaultmap, depend, nowait, in_reduction and device pointers go to target; firstprivate goes to both, to target only when the item is in no map or lastprivate clause; lastprivate and reduction go to X plus `map(tofrom:)` on target unless mapped; thread_limit and a modifier-less if go to every leaf that accepts them; the rest goes to X | the split directives parse at the version |
| `enter_exit_data` | each map clause of a target construct is preceded by `target enter data` (`to` for to/tofrom, `alloc` for from/alloc) and followed by `target exit data` (`from` for from/tofrom, `release` for to/alloc), so the construct's own map finds the items present | no nowait, if, device or depend clause; no present, iterator or mapper modifier |
| `num_teams_1`, `num_teams_3` | `num_teams` set on every construct with a teams leaf | no runtime routine reaches the result; no write runs once per team or thread (`redundant_execution`) |
| `thread_limit_32` | `thread_limit(32)` on every construct with a teams leaf | same as `num_teams_1` |
| `schedule_static_1`, `schedule_dynamic_3` | the schedule of every worksharing loop | no runtime routine reaches the result; no ordered clause |

## Running it

```
python3 -I tools/derive/expected.py fuzz --run c1 --workers 6     # results/expected/c1.jsonl
python3 -I tools/derive/expected.py catalog --workers 6           # results/expected/catalog.jsonl
python3 -I tools/derive/expected.py report                        # data/reports/expected-sources.md
python3 -I tools/derive/expected.py xnack0-command                # the copy-mode command
```

- `fuzz` takes the campaign's programs whose host reference run failed or disagreed with the model and whose model value no host run printed. It includes the host data of `results/fuzz/<run>/hostcheck.jsonl`. It runs elision, every applicable rewrite, the probe and the original on afar, cce19, cce20 and cce21 (`-O2`, `HSA_XNACK=1`, `OMP_TARGET_OFFLOAD=mandatory`).
- `catalog` takes the programs behind the support table's claim mismatches (`results/matrix.jsonl`) and every program with an open audit disposition (unaudited, unknown, unverified oracle not written; no atom is `weak`). It runs them on afar and cce19.
- `report` evaluates the stored records and writes the report.
- Copy mode (`HSA_XNACK=0`) needs a flux allocation. `xnack0-command` prints the command. When `results/expected/*.xnack0.jsonl` exist, `report` evaluates those runs as a separate copy-mode verdict (their own metamorphic family and probe witnesses, the same model and elision) next to the `HSA_XNACK=1` verdict. They never enter the `HSA_XNACK=1` evidence.

`tools/campaigns/fuzz.py host-check --run-id <run>` runs the host-path check of fuzz programs.

## Limits

- The version analysis is a model of the 5.2 data environment written for this project. Its rules are the ones listed above, at whole-variable granularity (an array section counts as the variable). A mistake in it would make elision agree with the model on a program whose OpenMP result differs. The mutants in `tests/engine/test_findings_afar.py` (removed maps, a missing `target update`, a lastprivate without `conditional`, a dropped implied map) pin the cases it must catch.
- A metamorphic stable witness needs two runs of one toolchain. With a shared bug in the original and every rewrite, a toolchain is a stable but wrong witness. For this reason metamorphic alone is never trusted.
- Under `HSA_XNACK=1` a runtime may answer `omp_target_is_present` without tracking presence (AFAR returned 0 after `target enter data`). The calibration then fails and the toolchain is no probe witness.
- A stable witness is only as informative as the rewrites that applied. Where the only applicable rewrite moves data (`enter_exit_data`), a toolchain that fails the original's schedule check fails it again, so the stable value shows the toolchain is deterministic, not that its scheduling is right.
- C programs are not covered.
