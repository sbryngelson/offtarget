What this changes, and why:

- [ ] A new or changed finding: `python3 -I tools/repo/check_findings.py` passes and every `TODO(human)` is replaced
- [ ] A new or changed rule, catalog entry or tool: `python3 -I -m pytest -q` passes (tests that need git-ignored inputs skip)
- [ ] The docs that describe it are updated (`docs/tooling/`)
- [ ] For a compiler problem: the compiler version banner, the command line, the GPU and the driver are in the finding or in this description

The rows that support a finding (the recorded results of running the program) must come from your own machine (`CONTRIBUTING.md`, "Add or correct a finding"). If you cannot run it, open an issue instead and attach your output.
