# The offload-issue site

The site is static. Its home page, `index.html`, is the issue list, with every compiler family
selected; the compiler buttons add or remove a family, and a link carries the selection as
`?fam=cce,afar`. `issues.html`, the list's former address, forwards to `index.html` with its query.
It is built from the findings (`data/findings/`) and the finding matrix
(`data/vendor/checks/`), and the build needs no compiler, GPU or measurement file.
[publishing.md](publishing.md) says how the site is deployed.

## Build

    tools/site_publish.sh OUT_DIR [--repo-url URL]                 # build and check
    python3 -I tools/site/site_build.py results/site [--repo-url URL]   # build only

`tools/lanes/wingtip_offline.sh site-build` runs the build alone on wingtip.

| option | effect |
|---|---|
| `--repo-url URL` | each issue page links to its finding's source file and to the issue forms (dispute or support its legality, report it fixed, report a mistake) |
| `--source-branch NAME` | branch those links point into (default `master`) |

`OUT_DIR` of `site_publish.sh` must be new or empty.

## Inputs

Everything the build reads is committed, so a clean clone without `results/` builds the same
site. `MANIFEST` in `offload/engine/site/inputs.py` lists the inputs.

| input | content |
|---|---|
| `data/findings/` | every finding whose `site:` block has no `not-a-compiler-issue` or `out-of-scope` disposition and no `hide` ([AUTHORING.md](../../data/findings/AUTHORING.md), "The site: block") |
| `data/vendor/checks/results-compact/`, `results-site/` | the finding matrix |
| `data/vendor/checks/cases.json`, `cases-site.json` | the cases the matrix runs |
| `site/inputs/atoms.json.gz` | the feature-support data, which is the device-scope rows of the dashboard's atom table |
| `site/inputs/citations.json` | the verified specification citations of each published finding |
| `site/templates/`, `site/static/` | page template, scripts, styles |

Regenerate `site/inputs/` on a machine that has `results/`. The second command reports when they are stale.

    python3 -I tools/site/site_inputs.py             # or: tools/lanes/wingtip_offline.sh site-inputs
    python3 -I tools/regenerate.py --check site-inputs

If `citations.json` lacks a published finding or an input is missing, the build stops instead of
producing a smaller site.

## Leak guard

`offload/engine/site/scrub.py` keeps user names, host names and private paths off the site.

- The build refuses to write a file that contains one (`leaks`).
- `tools/site/site_check.py` scans every built file and every rendered page for the same patterns.
- Finding headers and feature-support notes may cite internal work items or use internal working
  vocabulary. The rules `unjargon` and `unprocess` rewrite those phrasings out of the built pages,
  one rule per phrasing. The findings and `site/inputs/` are not changed.
- A work-item reference with no rule stops the build. A working-vocabulary word with no rule fails
  `tests/site/test_site_inputs.py` but does not stop the build, because words such as an OpenMP
  lock's "owner" or an AMD "agent handle" are legitimate.
- `tests/site/test_site_inputs.py` holds the rules and their expected results.
- The guard lets `--repo-url` through on purpose. The same name anywhere else is a leak.

## Fill the matrix

A matrix cell without a recorded run shows "unknown (not run)". These commands fill the cells.

    python3 -I tools/derive/finding_matrix.py plan     # runs each cell still lacks
    tools/jobs/run_site_matrix.sh tuolumne a    # pbatch; also b, c, d
    tools/jobs/run_site_matrix.sh wingtip a 0   # environment a, GPU 0
    python3 -I tools/derive/finding_matrix.py pack     # results/site-*.jsonl -> results-site/*.jsonl.gz

Commit `data/vendor/checks/results-site/` and rebuild.

- Environment `c` runs as its own job so that it lands on a different node than `a`.
- On wingtip, run the matrix in a lane of its own (`WINGTIP_LANE=site-mx
  tools/lanes/wingtip_offline.sh ...`) and start no other step in that lane until the runs end.
  Every `wingtip_offline.sh` step re-syncs its lane with `rsync --delete`, which removes the
  results and logs of a running matrix. Copy `results/site-wingtip.*.jsonl` back before packing.
  [wingtip.md](wingtip.md) has the details.
- `CASES=id,id` narrows every branch of `run_site_matrix.sh` to those derived cases (their
  reproducer and control). The vendor cases are then not run.
- A finding's control is the `control:` line of its `site:` header. It runs only when its case
  asks for it. `python3 -I tools/derive/finding_matrix.py cases --control harvest/NAME.c` adds it
  to `cases-site.json`. `tools/repo/check_findings.py` then needs a recorded passing control row.
  Before committing the case, run
  `GCC=1 VARIANTS=control CASES=<case id> tools/jobs/run_site_matrix.sh wingtip ENV GPU`, and the
  same with `tioga`. Copy `cases-site.json` and `run_site_matrix.sh` to the wingtip lane and the
  Tioga copy first.

GCC has two toolchains on the site. `gcc` covers the AMD GPUs: the MI300A in both memory modes
(GCC runs on the device at `HSA_XNACK` 0 and 1 there) and the MI250X, the MI300X and the MI350X in
copy memory, whose installs are its twins (`gcc_g90`, `gcc_mi300x`, `gcc_mi350x`); the site rows of
all four say `gcc` and the machine gives the GPU. `gcc_sm80` covers the A100 in separate memory. The runs take every case, vendor and
derived, run the reproducer only, and write `results/site-<machine>-gcc.<env>.jsonl`. On the AMD
machines other than Tioga, `GCC_ROOT` and `GCC_ROCM` name the install and the ROCm it loads.

    GCC=1 tools/jobs/run_site_matrix.sh wingtip a 0
    flux run -q pdebug -N1 -n1 -t 60m --job-name=compile-test-gcc-site-a \
      tools/jobs/run_site_matrix.sh tioga a

Tioga has no batch queue for this account. Each environment is one supervised interactive
`pdebug` job of at most an hour, run one at a time from the `/p/vast1` copy. MI250X cells without
a run stay "unknown (not run)".

## Check

    python3 -I tools/site/site_check.py results/site [--repo-url URL]

The check exits 1 on any problem. It tests the following.

- Every in-site link resolves, and no file contains a leak.
- In headless Chrome at 1280 and 420 px, it loads the index, one issue page per kind, every
  compiler page, feature support (a known construct and an unknown one, which must show a
  message) and the method page. It fails on a script error, a failed load, sideways scroll, an
  empty main region, or a leak in the rendered text.
- On the index, it clicks every filter and sort control from each compiler family's view (where a
  family button adds that family's issues, and the family's own button changes nothing), and compares the rows the list shows with `data/issues.json`. The
  expected rows are computed in `site_check.py`, not by the page's script. A click that changes
  nothing, empties the list or shows rows other than the data's is a problem. If the data says a
  click changes nothing (for example "Fortran" where every issue is Fortran), the check lists the
  click but does not count it.
- "Copy link" must say it copied or show the link selected.
- `issues.html?fam=gcc&q=map` must land on `index.html` with the same query.

The check needs node 22 or newer and Google Chrome or Chromium. Without them it runs only the
link and leak checks, and says so.

Run the browser check as a short foreground job on a Tuolumne compute node, with node from
`~/.nvm` on `PATH`:

    flux run -q pdebug --job-name=compile-test-site -N1 -n1 -t 15m python3 -I tools/site/site_check.py results/site

`pdebug` suits this job because you read the answer at once. Allow about 10 minutes of queue wait.
wingtip has no Chrome, so its test lane skips the browser tests.

The driver `tools/site/site_check.mjs` starts Chrome in its own process group. When the check
ends, the driver sends the group SIGTERM and, after a 2 s grace period, SIGKILL, so a surviving
renderer cannot make the job outlive the script. If a job still outlives the script, read its
log. The summary line is the result.
