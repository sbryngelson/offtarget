# tools/repo

Checks and lists that keep the repository consistent. [maintainers](../../docs/maintainers.md) gives an overview.

| file | role |
|---|---|
| `check_findings.py` | each finding's header claims against the recorded rows |
| `check_citations.py` | spec citations of findings, vendor drafts and rulings against the spec text |
| `docstring_report.py` | module docstrings over the length limit (`--write` rewrites the allowlist) |
| `docstring_allow.txt` | modules allowed to exceed that limit |
| `scrub_vocab.py` | report or remove internal work-item vocabulary from text |
| `trace_reads.py` | list the repository files a command opens |
| `bundle_manifest.txt` | files an installed `offload` carries; checked by `tests/test_bundle.py` |
| `path_allowlist.txt` | paths named in tracked text that are not files, one `file<TAB>path` per line |
