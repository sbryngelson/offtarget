# offload/engine/harvest

This package converts tests from LLVM `offload/test` and AOMP `test/smoke` and `test/smoke-fails` into self-checking catalog programs. Each test is inventoried as data and filtered, with a recorded reason for every drop. It is converted by appending a self-check built from its FileCheck lines.

The entry point is `tools/campaigns/harvest.py`. `harvest2/` reuses `convert.py` for other sources.

It reads the cloned test trees under `corpus/`. It writes converted programs with a provenance header, and the drop reasons.

- `inventory.py` reads the tests (files with a `RUN:` line) without running them.
- `filters.py` `classify` assigns drop reasons, one of them primary.
- `checks.py` parses FileCheck directives and matches program output against them.
- `convert.py` builds the program for one RUN variant; `holdout_by_code` assigns the holdout.
- `c_runtime.py`, `f_runtime.py` the C and Fortran self-check text appended to a converted test.
- `history.py` the commits that added or fixed a test and the issues they name.

Read `convert.py` first.
