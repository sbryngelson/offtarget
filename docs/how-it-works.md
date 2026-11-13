# How it works

## Findings

A finding is one file in `data/findings/`. It holds a small program and a header that says what the program does,
what a correct compiler prints and what each compiler did instead. A program becomes a finding only when

- it is legal for the spec version it names, with the section cited and checked against the spec text;
- it is as small as the failure allows, and a control (a variant that changes one thing) passes;
- it was run on the real compiler and machine, in each memory mode the machine has, and the failure repeated;
- another compiler family runs it correctly, which is evidence that the program is legal but not proof.

`tools/reduce.py` shrinks a failing program and writes the controls. `tools/confirm.py` reruns a failure and matches
it against the findings already known. A person writes the title and the argument that the program is legal.

## The catalog

`catalog/` holds the programs behind the can-use tables: one small program per clause, directive or construct, for
each spec version. Each program is run on every compiler, machine and memory mode, and each cell gets a state:
`correct`, `unsupported` or `unknown`. `unknown` means the run did not settle the question, for example because the
program ran on the host. Programs that run but give a wrong answer, crash or hang are findings instead, and appear
in `offload issues`. The runs and their recorded results are in `results/`, which is not in the repository. The
tables built from them are.

## One source for the command line and the website

`offload can-use` and `offload issues` read JSON that is written by the same code that builds the website
(`offload/engine/site/`), from the same findings and tables. `pip install` builds that JSON into the package, except
for the per-issue pages. A checkout builds it on first use and caches it in `.offload-cache/`. The website shows the
same data as static pages, built by `tools/site_publish.sh`.
