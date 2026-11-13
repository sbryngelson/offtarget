# data/vendor

The re-runs of every finding on the current compiler releases. The site's issue pages and the finding headers
are built from them. The report drafts written from the re-runs are not published.

| path | what |
|---|---|
| `checks/cases.yaml`, `checks/cases.json`, `checks/cases-site.json` | each case: the finding it reproduces, the reproducer and its control (a one-change variant that gives the expected result) |
| `checks/src/` | the reproducers and controls that were compiled |
| `checks/build.py`, `checks/run_checks.py`, `checks/run_*.sh` | build the reproducers from the finding files and run them in the reproduction gate's environments |
| `checks/results-compact/`, `checks/results-site/` | one JSON line per compile and run, without compile logs, host names or private paths |
| `checks/summary.json`, `checks/findings.txt` | the verdict per case, and the finding list the runs cover |
| `checks/dispositions.py` | findings that are not compiler defects, with the reason |
| `checks/probe/` | the runs that settled a disputed case |
