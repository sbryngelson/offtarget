# Contributing

This repository collects legal OpenMP and OpenACC device-offload programs, in C and Fortran, that a compiler gets
wrong, together with the `offload` command that looks them up. Only device offload is in scope
([docs/scope.md](docs/scope.md)). You do not need access to the project's GPU machines to help. A clear bug report is
useful on its own, and you can add a finding with results from any compiler you can run.

## Report a compiler problem

Open an issue with the "Compiler problem" form. It asks for:

- The smallest legal program that shows the problem, as one file in C or free-form Fortran. Say which OpenMP or OpenACC version it follows and, if you can, which section of the specification makes it legal. If it is legal only because of a clause you added, say so.
- The compiler's full version banner (`--version`) and the module or container it came from.
- The exact command line, including the offload flags, the optimisation level and the device architecture.
- The machine, the GPU model and the driver or ROCm/CUDA version. For AMD GPUs, give the `HSA_XNACK` setting; for NVHPC, the `-gpu=mem:` setting.
- What you expected and what you got: the compiler message, the crash signal, the hang or the wrong values. Say whether it happens every time and whether another compiler runs the program correctly.
- If you have one, a version of the program with a single change that passes, such as a clause removed or a construct unwrapped. It shows which construct is at fault.

Before opening an issue, search the existing ones with `offload issues WORDS`. `offload issues --help` lists the filters (`--compiler`, `--kind`, `--status`, `--show`). Programs that rely on a compiler extension or on undefined behaviour are out of scope.

## Add or correct a finding

A finding is one file in `data/findings/`. It holds the program and a header describing what fails, where, and the evidence. The facts in the header are generated from recorded results and checked against them. [data/findings/AUTHORING.md](data/findings/AUTHORING.md) describes the format and the parts you write by hand.

You produce the results by running the program on your own machine, so you need the compiler and, for a device run, the GPU. The repository does not assume any particular machine. You tell it where your compiler is installed and how to reach your machine in a settings file of your own: see "Your machines and compilers" in [docs/tooling/setup.md](docs/tooling/setup.md), and the template [catalog/local.example.yaml](catalog/local.example.yaml).

1. Register the compiler you will use. If the catalog already lists that release, you only add its install path; a
   compiler built for another offload target also needs its flags ("Your machines and compilers" in
   [docs/tooling/setup.md](docs/tooling/setup.md) shows both). A new machine, compiler or release needs a catalog
   entry; see "Add a compiler or a compiler release" in [docs/tooling/contributing.md](docs/tooling/contributing.md).
   If you have a compiler of another family that can check the program (a front end, not the one under test), list
   it under `independent_checkers`: the reducer then keeps only candidates it accepts.
2. Reduce the failing program with [tools/reduce.py](tools/reduce.py):
   `python3 -I tools/reduce.py --program FILE --target TOOLCHAIN/MODE --name NAME --out WORK`. It runs the program
   on your machine, shrinks it to a small reproducer `WORK/NAME.c` (or `.f90`) plus variants that differ by one
   change and pass on the same compiler (the controls, in `WORK/controls/`), and writes the results to
   `WORK/rows.jsonl`. Targets are the toolchain ids in [catalog/toolchains.yaml](catalog/toolchains.yaml). Without
   an independent checker, add `--no-witness`; a maintainer checks legality later. If no variant passes (the
   compiler rejects them all, or they run on the host), `controls/` stays empty; that is allowed, and the draft
   says so.
3. Draft the finding as a proposal with [tools/new_finding.py](tools/new_finding.py):
   `python3 -I tools/new_finding.py WORK/NAME.c --campaign NAME --rows WORK/rows.jsonl --control WORK/controls/FILE
   --name SLUG --dir FOLDER --proposal`. Leave out `--control` if `controls/` is empty. `--dir` is the folder under
   `data/findings/` the finding will belong in (`gcc`, `nested`, `oop`; see
   [data/findings/README.md](data/findings/README.md)). `--proposal` writes the finding, its controls and a copy of
   its rows to `data/findings/proposed/`, where nothing publishes it.
4. Fill in every `TODO(human)`: the title, the specification citation and the quoted passage, the legality
   statement, and the title and summary in the `site:` block (keep the `title:` and `summary:` keys). Write a
   citation as version, section sign, printed page and margin lines, with the quoted passage before it, for example
   `"the quoted words" (5.2 §13.2 p.276 l.21-23)`; text in another form is not checked. The draft's compiler line
   comes from the catalog entry of the toolchain you ran: if your compiler is another release, add it as one
   ("Add a compiler or a compiler release") so the header names the right version. The compiler under test can
   never be the evidence that a program is legal, and neither can gcc or gfortran.
5. Run [tools/repo/check_findings.py](tools/repo/check_findings.py) (all findings, `proposed/` included, or one
   named relative to `data/findings/`, such as `proposed/NAME.c`). Without a `results/` directory it runs with
   `--mode committed` and checks the header's form and the `TODO(human)` items, not the counts. If you have the
   specification PDFs in `spec/` ([docs/tooling/setup.md](docs/tooling/setup.md)), also run
   [tools/repo/check_citations.py](tools/repo/check_citations.py) on the file; without them it stops and says so,
   and a maintainer checks the citation.
6. Open a pull request with the files in `data/findings/proposed/`. Say which flags you used if they differ from the
   catalog's, and whether the program ran on a GPU.

A maintainer then reruns the program in the four gate environments (another build directory, another node, a
repeat), runs it on the other compilers, adds the site rows and citations, checks legality, and moves the finding
out of `proposed/` with its index entry. Those steps need the project's machines and the git-ignored `results/` and
`spec/`, which is why the proposal does not need them.

If you cannot run the program yourself, open an issue ("Compiler problem") and the maintainers will try to reproduce
it.

To correct a finding, edit its header and run the same check; it fails on any claim the recorded results do not
support. If you cannot produce new results, use the "Mistake on an issue or feature page" form and attach your
output.

### What happens to a new finding

A maintainer runs the independent legality review on it ([tools/review/](tools/review/README.md)). Readers who see
only the program, the specification text and the observed result, never the legality argument in its header, judge
whether the program is legal and whether the specification requires the result. The readers are language models,
each checked against a decoy with a known answer, and every passage they quote is checked against the
specification. Until two of them agree, the website shows the finding as "not independently confirmed"; if one finds
it not legal, it shows as "contested", with the reason. Editing the program later resets this until it is read again.

Every pull request runs the `check` workflow, which runs `check_findings.py` and the tests that need neither a GPU nor a vendor compiler. A pull request that changes a finding, a rule or a tool should follow the checklist in the pull request template.

## Dispute a finding, or report it fixed

Each issue page on the website links to three forms that name the finding for you:

- "Dispute or support a finding's legality": the program is not legal, the specification does not require the
  result it expects, or (for a contested or unconfirmed finding) it is legal and the result required. Quote the
  passage (version, section, page) and the lines of the program it applies to. The argument goes to new readers
  next to an existing reading, as in "What happens to a new finding"; a finding shown wrong is corrected or
  withdrawn.
- "Fixed in a newer release": give the release's `--version` output, the command line, the GPU and the output. A
  maintainer reruns the reproducer on that release and records the result; the issue then shows as fixed there.
- "Mistake on an issue or feature page": anything else a page or the feature-support table gets wrong.

`offload issues --legality contested` (or `unconfirmed`) lists the findings whose legality is in doubt. The forms
are in `.github/ISSUE_TEMPLATE/`; the dispute form asks for the finding, the claim, the specification passage and
the program lines it applies to, and your reasoning.

## Run the tests

You need Python 3.10 or newer and the packages in `tools/repo/test_requirements.txt`, which include pytest-xdist
for the parallel run the `check` workflow uses.

    python3 -m venv .venv
    .venv/bin/pip install -r tools/repo/test_requirements.txt
    .venv/bin/python -I -m pytest -q -rs -n auto -m "not gpu"

The commands run Python with `-I`, which ignores packages installed with `pip install --user`; a virtual environment
works. Stage a proposal (`git add`) before running the tests.

With 16 workers the suite takes about a minute and a half, with 4 about nine minutes; one process at a time it
takes longer. Tests that build with the host gcc or gfortran skip when that compiler cannot link an OpenMP `teams`
program, as some installs cannot.

Some tests need files that are not in the repository, and they skip with a message naming what is missing. The markers are `needs_spec` (the OpenMP and OpenACC specification PDFs in `spec/`), `needs_corpus` (clones of third-party test suites in `corpus/`), `needs_results` (measurements in `results/`) and `needs_compiler` (an installed vendor compiler). `needs_linux` marks tests that use Linux process control and `needs_gcc` those that need GNU gcc as `gcc`; on macOS both skip. In the public repository, `needs_bench` and `needs_commit` mark tests that need the benchmark sets or older history. A fresh clone passes with those tests skipped. Tests marked `gpu` need a GPU on the machine; `-m "not gpu"` leaves them out. [docs/tooling/setup.md](docs/tooling/setup.md) says where to get the missing inputs. The measurements cannot be downloaded, so the tests that read them only run for the maintainers.

## Conventions

- Fortran findings are free-form, with no line longer than 132 characters, comments included ([tests/engine/test_findings.py](tests/engine/test_findings.py)).
- Third-party programs keep their licence and header; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- None of the tooling files bug reports or posts anything outside the repository. Report a problem to a vendor through the vendor's own channel.

## Maintainer documentation

- [docs/maintainers.md](docs/maintainers.md): the layout, adding a finding, regenerating data.
- [docs/tooling/](docs/tooling/): [contributing.md](docs/tooling/contributing.md) (runbooks and standing rules), [setup.md](docs/tooling/setup.md), [regenerate.md](docs/tooling/regenerate.md), [confirm.md](docs/tooling/confirm.md), [toolchains.md](docs/tooling/toolchains.md).
- [docs/provenance.md](docs/provenance.md): where the programs, the measurements and the model come from.
- [docs/how-it-works.md](docs/how-it-works.md): how a failure becomes a finding.
