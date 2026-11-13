# The bug confirmer

The confirmer turns the evidence the project already collects into a verdict for each failure, shrinks and deduplicates it, and drafts the finding. A person decides only the cases it labels `needs_human`. The rules are vendor-neutral, because machines, memory modes and toolchains are data ([toolchains.md](toolchains.md)).

The command line is `tools/confirm.py` and the library is `offload/engine/confirm/`.

## Commands

```
python3 -I tools/confirm.py case FILE... --toolchain TC [--mode unified|copy|managed] [--arch A]
        [--expected V] [--run] [--repeats N] [--minimize] [--draft]
python3 -I tools/confirm.py batch --from SOURCE... [--filter F] [--toolchains TC...] --out OUT
        [--run] [--minimize] [--draft] [--shard N] [--store PATH]
python3 -I tools/confirm.py decide --batch BATCH... --out OUT [--decisions FILE]
python3 -I tools/confirm.py index [--scope [--write]] [--batch BATCH]
python3 -I tools/confirm.py backlog [--batch BATCH] [--write]
python3 -I tools/confirm.py triage
python3 -I tools/confirm.py witness [--programs P...] [--batch BATCH]
python3 -I tools/confirm.py validate [--live]
python3 -I tools/confirm.py regress plan|fuzz|diff|confirm|report --toolchain NEW --like OLD [--submit]
python3 -I tools/confirm.py promote DRAFT NAME
python3 -I tools/confirm.py exec          # remote runner entry point
```

`case` confirms one program on one toolchain and mode. `batch` confirms every failing cell of the given sources (`results/matrix*.jsonl`, `baseline*.jsonl`, `acc_matrix*.jsonl`, `results/fuzz/*/programs.jsonl`). The shipped batches are `results/confirm/batch_*.jsonl`. `tools/jobs/run_regen_confirm.sh` regenerates them ([regenerate.md](regenerate.md)).

## Pipeline

1. **Ingest** (`ingest.py`, `programs.py`). Each failing result row becomes a `Case`. A case holds the program (catalog id, omp_vv path, fuzz seed or file set, with its hash and C/Fortran port), toolchain, machine, arch, memory mode, optimisation level, outcome class and source row.
2. **Signature** (`findings.py`). A failure is identified by its toolchain family, outcome class, normalized message or crash site, and construct set. Two failures become one finding when they have the same family, class and message (compile time) or overlapping key constructs (run time, `findings.same_signature`). The new case is then attached to the finding as an instance. In fuzz programs, a run-time failure is an instance only if it involves a key construct that is rare in the fuzz corpus (`findings.COMMON_FUZZ`) or matches the finding's own runtime message (the `! message: <regex>` header line). A failure that prints a different runtime error (`findings.RUNTIME_MESSAGE`) is related to the finding but is not an instance.
3. **Legality gate** (`legality.py`). A program is legal by construction, legal by the checkers (catalog grammar, restriction rules, front-end checkers), illegal, or unknown. An illegal program is `our_bug`. An unknown one goes to `needs_human`. A compiler under test never serves as its own legality checker.
4. **Rules** (`rules.py`, `catalog/confirm_rules.yaml`). The rules are tried in order, and the first one whose conditions all hold decides. The collectors a rule needs run only when the rule is reached, cheapest first, and they reuse stored evidence.
5. **Actions** (`engine.py`, `minimize.py`, `draft.py`). The confirmer minimizes the program, keeping the same verdict under the same rules, then dedupes and writes a draft.

## Machines and memory modes

A mode is `unified` (host and device share memory), `copy` (separate copies) or `managed` (NVHPC `-gpu=mem:managed`). A machine lists only the modes it has. A mode it lacks is `not_applicable`, which is neither a failure nor missing evidence. `catalog/machines.yaml` gives each machine its arch, device, `access` (`local` or an ssh entry with a clone root), `scheduler` (`flux`, `slurm`, `direct` or local) and `headline_mode`. For each mode it gives either `env` (on AMD, `HSA_XNACK`) or `flags` (NVHPC), and a `row_key`, the value stored in the `xnack` field of a result row. Rules never name XNACK.

`machines.py` reads this file. `jobs.py` submits jobs through `FluxScheduler`, `SlurmScheduler`, `DirectScheduler` or `LocalScheduler`. `execute.py` runs one program (compiled once, run k times) with `LocalRunner` or `RemoteRunner`. `RemoteRunner` connects by ssh to the machine's clone and runs `tools/confirm.py exec`. Remote commands on wingtip go through the cap described in [wingtip.md](wingtip.md).

## Data formats

**Case** (`model.Case`): `case_id`, `program` (kind, ident, version, lang, model, sha256), `toolchain`, `machine`, `arch`, `mode`, `opt`, `outcome`, `reason`, `value`, `ran_on_host`, `flaky`, `repeats`, `source` (file and line).

Outcome classes (`model.OUTCOMES`): `rejected`, `ice`, `crash`, `run_error`, `timeout`, `wrong_answer`, `fell_back_to_host`, `accepted_ignored`, `harness_error`, `correct_on_device`, `unobservable`.

**Evidence** (`model.Evidence`) is one line of `results/confirm/evidence.jsonl`, which is append only and keyed by program hash, toolchain, arch, mode, opt, offload policy and variant. Its fields are `collector`, `key`, `runs`, `value`, `status` (`value`, `no_value`, `inapplicable` or `not_applicable`) and `provenance` (command, host, date, modules, source row). A runner failure is not evidence. It is retried once, then recorded as missing and never cached.

**Result** (JSON per case): `case`, `verdict`, `rule`, `reason`, `evidence`, `withdrawn`, `citations`, `actions`, `drafts`.

**Findings index** (`data/findings/index.yaml`) has one entry per finding, with the fields `file`, `toolchains`, `outcome`, `message`, `modes`, `arch`, `expected` and `scope` (`device` or `out_of_scope`). `index --scope` re-matches every stored failing cell of the batch against the index and derives each finding's `modes` and `arch` from its linked cells. It exits 1 when the index differs, and `--write` rewrites the index. A finding with no linked cell keeps its recorded scope. `tests/confirm/test_confirm_outputs.py` fails when a linked cell lies outside the finding's scope.

## Collectors

The collectors are listed cheapest first (`collectors.COLLECTORS`).

| collector | cost | gives |
|---|---|---|
| `stored_repeats` | 0 | the case row's own repeats (`flaky`) |
| `expected_record` | 0 | stored expected verdicts and dispositions (`catalog/expected_triage.yaml`) |
| `model` | 0 | the program's own oracle, the fuzz model checksum, a finding's stated output |
| `derivation` | 0 | the hand derivation in a catalog program's header |
| `other_toolchains` | 0 / 3 | the same program on the machine's other toolchains |
| `other_mode` | 0 / 3 | the same toolchain in the machine's other modes |
| `other_arch` | 0 / 5 | the same compiler on another arch (stored rows, else `RemoteRunner`) |
| `port` | 0 | the C/Fortran port's stored rows |
| `elision` | 1 | sequential elision (`offload.engine.expected`), Fortran |
| `repeats` | 2 | k more runs of the failing cell |
| `host_run` | 2 | `OMP_TARGET_OFFLOAD=disabled` on the failing toolchain and another family |
| `opt0` | 3 | the failing cell at -O0 |
| `metamorphic` | 4 | spec-equivalent rewrites (`offload.engine.transforms`) |

## Rulings registry

`catalog/rulings.yaml` holds the project's readings of the spec and its scope decisions, which rules cite by id. Each entry has these fields:

- `id` and `kind` (`legality`, `spec_reading`, `implementation_defined`, `unspecified`, `scope`, `oracle`, `mode`, `process`).
- `rulings_md`, a phrase that must occur in `data/reports/rulings.md`.
- `citations`, each with a version, section, page and quote. The quote must occur on the cited page of the spec text.
- `applies`, naming programs, atoms and constructs.
- `decides` (optional), the outcome classes and releases that the ruling settles by itself.
- `test`.

`offload/engine/confirm/registry.py` loads and checks the file. A rule that needs a reading with no entry gives `needs_human`.

## Decision rules

`catalog/confirm_rules.yaml` is versioned data. Each rule has an `id`, `verdict`, `rationale`, `cite`, `needs` (the collectors it uses) and `when` (named predicates of `rules.PREDICATES` over the facts in `facts.py`). The verdict `ruling` means the verdict comes from the registry entry that `decides` the case.

Verdicts: `compiler_bug`, `copy_mode_failure`, `unified_memory_failure`, `needs_unified_memory`, `requirement_refused`, `arch_specific`, `our_bug`, `unspecified`, `unsupported`, `unsupported_everywhere`, `noncompliant`, `flaky`, `environment`, `not_a_failure`, `needs_human`.

| rules | verdict | when |
|---|---|---|
| R01 | environment | harness error, runner or ssh failure |
| R02 | not_a_failure | the cell passed |
| R03 | our_bug | the legality gate says illegal |
| R04, R04b | needs_human | legality unknown; the reproduction gate did not confirm the failure |
| R05 | unsupported | not-implemented rejection, or accepted and ignored |
| R09 | flaky | some repeats pass and some fail |
| R10 | compiler_bug | internal compiler error |
| R10b | compiler_bug | link failure on symbols the compiler's own code needs, or a compile hang, on a legal program |
| R10r, R11r, R19r | by ruling | a registry entry with `decides` settles the case |
| R11a | unsupported | rejection of an OpenMP 6.0 form with no recorded vendor claim |
| R11c | unsupported | rejection of a form a later OpenMP version added to an earlier construct (`catalog/later_forms.yaml`) with no vendor claim |
| R11d | unsupported | rejection of a feature the vendor documents as unsupported (ICE, link failure and hang excluded) |
| R11 | compiler_bug | rejection, link failure or hang while another family compiles it |
| R12a | compiler_bug | every family rejects, but an independent offload-compiler witness accepts, the spec text is quoted and the vendor claims the feature |
| R12 | unsupported_everywhere | every family rejects a legal program (not for fuzz programs) |
| R12b | needs_human | a compile failure nothing else decides |
| R19b | compiler_bug | host fallback under mandatory offload while another family runs on the device |
| R07 | needs_unified_memory | run-time failure in copy mode of a program that needs zero-copy memory |
| R08 | requirement_refused | copy mode, `requires unified_address`, run ends early, unified passes |
| R06, R15 | unspecified | the program's result is unspecified or implementation defined (registry or stored triage) |
| R13 | our_bug | elision and every comparable device cell agree against the program's claim |
| R13a, R13c, R14 | needs_human | contested oracle; weak noncompliance evidence; independent expected-value sources disagree |
| R13b | noncompliant | fuzz wrong answer that no host build reproduces, host builds of two or more families ran |
| R16 | compiler_bug | copy-mode failure of a program whose check is blind in unified mode, trusted expected value |
| R17, R18 | copy_mode_failure, unified_memory_failure | one mode fails, the other passes, the other arch does not pass in that mode |
| R19 | arch_specific | the same compiler passes on another arch in the same mode |
| R20 | compiler_bug | deterministic run-time failure against a trusted expected value (two independent sources and an executed witness) |
| R21, R22, R22b, R99 | needs_human | too few repeats; expected value provisional or derived; metamorphic runs dispute the value; nothing decides |

R12a needs a configured witness, meaning an independent compiler whose front end accepts the program. `catalog/legality_witness.yaml` and the `independent_checkers` of `catalog/machines.yaml` list offload compilers flagged `witness_only: true`, and `tools/confirm.py witness` runs them. gfortran and gcc with `-fopenmp` are not witnesses.

For a presence or overlap abort (`facts.PRESENCE_ABORT`), R20 accepts only a run that enforces the present table (CCE, or AFAR in copy mode).

## Drafts and promotion

`results/confirm/drafts/<case id>/` holds `finding.md`, the minimized program `program.<f90|c>` and `result.json`. `finding.md` lists the compilers, versions, arch, modes, expected versus actual result, the evidence table, the rule id, and the ruling citations (or "citation needed"). `promote DRAFT NAME` copies the program to `data/findings/` with the header as comments and appends the index entry. Promotion is never automatic.

## Regression mode

`regress plan|fuzz|diff|confirm|report --toolchain NEW --like OLD` compares a new toolchain with an old one. `plan` prints or submits the run jobs (`tools/jobs/run_regress.sh`), which cover the catalog per language and mode, the omp_vv baseline and a fixed fuzz sample. The rows go to `results/confirm/regress/NEW/`. `diff` compares NEW with OLD's stored rows cell by cell. `confirm` reruns both toolchains on each differing cell and applies the rules. The report is written to `results/confirm/regress/NEW/report.json` and `data/reports/confirm-regress-NEW.md`.

## Vendor claims, mismatches and omp_vv flags

1. `python3 -I tools/derive/claims.py ingest` checks the hand mapping (`catalog/omp/claims.yaml`, `catalog/acc/claims.yaml`) against each vendor document edition (the `documents` of `catalog/vendor_claims.yaml`) and writes `catalog/vendor_claims_generic.yaml`. It records a claim for each toolchain whose edition contains the quote.
2. `python3 -I tools/derive/support_table.py [--lang c | --model acc]` lists the mismatches between claims and measured cells.
3. `python3 -I tools/confirm.py triage` confirms the contradicting cells of each mismatch and the cells of each omp_vv flag, assigns dispositions, and generates the triage tables and `docs/upstream.md`. Cases the rules leave as `needs_human` are decided in `catalog/triage_27b.yaml`. A seeded sample of the decided cases in each class is re-read (`spot_checks`).

## Adding a machine or toolchain

A machine is an entry in `catalog/machines.yaml`, and a toolchain or family is an entry in `catalog/toolchains.yaml`. Vendor claims need a document entry in `catalog/vendor_claims.yaml` and, for a new document format, a parser in `offload/engine/confirm/claims.py`. The compiler message tables of each family (`PATTERNS`, `NOTES` and `ERROR_TERMINATION` in `offload/engine/harness.py`) need captured compiler output. `facts.PRESENCE_ABORT`, `findings.RUNTIME_MESSAGE` and `findings.site_of` need the family's runtime and ICE texts. [contributing.md](contributing.md) gives the steps and checks.

Some code is still vendor-specific. That is HSA_XNACK as the AMD mode switch in `machines.yaml`, the compiler recipes in `offload/engine/toolchains.py`, the message tables in `offload/engine/harness.py`, and the ICE site extractors in `findings.site_of`.
