# data/findings

Each file here is one finding: a small, legal OpenMP or OpenACC program that a compiler gets wrong on a GPU, with a
header that says what the program should print, what each compiler did instead, the specification text that makes
the program legal, and the recorded runs behind those facts. The website and `offload issues` are built from these
files; they are the easiest way to read them.

| folder | where the programs came from |
|---|---|
| (top level) | written by hand, mostly from the catalog's feature programs and early campaigns |
| `catalog/` | catalog programs that the confirmer turned into findings |
| `fuzz/` | randomly generated programs, reduced |
| `stress/` | programs that scale one feature up (many clauses, large sizes) |
| `nested/` | structures with pointer and allocatable members mapped to the device |
| `oop/` | Fortran derived types and object-oriented features |
| `apps/` | reductions of failures in application codes (MFC and others) |
| `harvest/`, `fresh/` | public bug reports and upstream test suites |
| `gcc/` | GCC's own failures |
| `hecbench/`, `malloc/`, `dataenv/` | single campaigns: HeCBench benchmarks, device `malloc`, the data-environment rules |

`proposed/` holds findings proposed from outside the project, not yet checked by a maintainer; nothing there is
published.

`reviews/` holds the independent legality review of each finding that has one: blind readers, the decoys they
were checked with, and the verdict ([tools/review/](../../tools/review/README.md)).

A `controls/` folder beside a finding holds its controls: the same program with one change, which the same
compiler runs correctly.

`index.yaml` lists every hand-written finding with its compilers, outcome, message, memory modes and GPU
architectures; the confirmer (`tools/confirm.py`) matches new failures against it. [AUTHORING.md](AUTHORING.md)
explains how to write or correct a finding, including the optional `site:` block, and
`python3 -I tools/repo/check_findings.py` checks every header against its recorded runs.
