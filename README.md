# OffTarget

[![Website](https://img.shields.io/badge/web-offtarget.sh-1f5fbf.svg)](https://offtarget.sh) [![check](https://github.com/sbryngelson/offtarget/actions/workflows/check.yml/badge.svg)](https://github.com/sbryngelson/offtarget/actions/workflows/check.yml) [![PyPI](https://img.shields.io/pypi/v/offtarget?color=1f5fbf)](https://pypi.org/project/offtarget/) [![Python](https://img.shields.io/badge/python-3.10%2B-1f5fbf.svg)](https://pypi.org/project/offtarget/) [![License: MIT](https://img.shields.io/badge/License-MIT-1f5fbf.svg)](https://github.com/sbryngelson/offtarget/blob/master/LICENSE)

A catalog of small, legal OpenMP and OpenACC GPU-offload programs that real compilers get wrong on real GPUs, and
`offload`, the command that looks them up. The compilers are AMD's AFAR, HPE's Cray CCE, NVIDIA's HPC SDK and GCC;
the GPUs are AMD's MI300A, MI250X, MI300X and MI350X and NVIDIA's A100.

- `offload can-use FEATURE` shows which compilers and versions support a clause, directive or construct
  (`--list` prints the feature names).
- `offload issues [QUERY]` lists the known problems, each with its reproducer, the evidence for it and the
  independent review of its legality (`--legality contested` lists the disputed ones).

```
$ offload can-use clause.map.present
clause.map.present   OpenMP 5.2, Fortran
                   MI300A unified  MI300A copy  MI250X   MI300X   MI350X   A100 separate  A100 managed
AFAR 24.3.0        unknown         correct      correct  correct  correct  -              -
CCE 21.0.3         correct         correct      correct  -        -        -              -
NVHPC 26.9         -               -            -        -        -        unsupported    unsupported
GCC 16.2.0 (AMD)   unknown         unknown      correct  correct  correct  -              -
GCC 16.2.0 (A100)  -               -            -        -        -        correct        -
```

There is a table per specification version and language and a row per release (some left out here). Columns are
GPUs and memory modes: MI300A "unified" is `HSA_XNACK=1`, "copy" `HSA_XNACK=0`; the A100's are NVHPC's `-gpu=mem:`
settings. `-` means not run there; `unknown` means the runs did not give a clear answer.

## Install

You need Python 3.10 or newer; pip installs PyYAML, the one dependency. The tool does not download anything when it runs.

```
pip install offtarget
offload --help
```

From a checkout, `pip install .` installs it, and `python3 -m offload --help` runs it without installing; the first command then builds its data from the checkout, which takes about a minute.

## Where the answers come from

Each problem is a file in `data/findings/` holding the reproducer and the measurements behind it; the tool and the
website are built from these files. A failure counts only when it reproduces in another build directory, on another
node and in a repeat run, and each program's legality is read independently from the specification text by
language-model readers checked against decoys ([tools/review/](https://github.com/sbryngelson/offtarget/blob/master/tools/review/README.md)). See
[how it works](https://github.com/sbryngelson/offtarget/blob/master/docs/how-it-works.md), [usage](https://github.com/sbryngelson/offtarget/blob/master/docs/usage.md) and [docs/README.md](https://github.com/sbryngelson/offtarget/blob/master/docs/README.md).

## Limits

CCE ran on the MI300A and MI250X, NVHPC on the A100, AFAR on every AMD GPU, and GCC on the MI250X, MI300X, MI350X and A100. [Scope and limits](https://github.com/sbryngelson/offtarget/blob/master/docs/scope.md) has the details.

## Contributing

Open an issue to report a compiler problem, dispute a catalogued program's legality or report a fix; each has a
form, linked from every issue page on the website. To add or correct a finding with results from your own compiler,
see [CONTRIBUTING.md](https://github.com/sbryngelson/offtarget/blob/master/CONTRIBUTING.md); you do not need access to the project's machines.

## Licence

MIT; see `LICENSE`. `THIRD_PARTY_NOTICES.md` lists the third-party sources and their licences.
