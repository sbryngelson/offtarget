# offload/engine/harvest_known

This package extracts known compiler problems from outside reports and turns them into bug cases. The fetchers read public pages, and the text readers are pure functions over text.

The entry point is `tools/campaigns/harvest_known.py`.

It reads downloaded pages and cloned repositories, which are kept in the untrusted download area. It writes cases to `data/bench/harvest-known/hk-NNN.<f90|c>`, each with a header giving the source, the edits and the expected result.

- `centres.py` supercomputing centres' known-issues pages, live and archived.
- `forum.py` the NVIDIA HPC compilers forum, read-only through its JSON endpoints.
- `relnotes.py` PGI and NVHPC release notes, used to date TPR fixes.
- `apps.py` commits, pull requests and issues in open applications that add or remove a compiler workaround.
- `textscan.py` shared text scanning: offload model, language, compiler named.
- `cases.py` the harvested case format and its legality rows.

Read `textscan.py` first.
