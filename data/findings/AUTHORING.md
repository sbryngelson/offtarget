# Writing a finding

A finding is a file in this directory. It holds a legal device-offload program that a compiler gets wrong, and a
header that says what fails, where, and what evidence supports it. The header used to be written by hand, and some
claims had no recorded run behind them. Examples were a control with no row, "other compilers run it correctly" when
none had been run, wrong counts, and "fails the same way" for different messages. Now the facts are generated from
the recorded rows (the result lines saved for each run) and checked against them.
[CONTRIBUTING](../../CONTRIBUTING.md) describes the conventions for the whole repository.

## Make one

First produce the rows. Run the reduction and its one-change controls (variants of the program that differ by one
edit and pass) and, for a campaign program, the gate, which reruns each failure in four environments.
`tools/reduce.py` makes the reduction, the controls and their rows from a failing row or a fuzz seed; see
"Reduce a failing program" in [CONTRIBUTING](../../CONTRIBUTING.md). The rows are in `results/<campaign>/*.jsonl`
(harness rows, gate reruns and probe rows) or in the site and vendor-check rows (`data/vendor/checks/results-compact`
and `results-site`). Then run the following from a compute node or a wingtip lane, never from a login node:

    python3 -I tools/new_finding.py REDUCTION.c --campaign nested-data \
        --rows results/nested/red/tuo*.jsonl results/nested/red/gate_*.jsonl \
        --control results/nested/red/j1-ctl.c results/nested/red/j2-ctl.c \
        --programs nd-c-omp-one-chain-d3-d6c766c9 --gate results/nested/main/gate_reruns*.jsonl \
        --name cce-c-struct-and-nested-pointee-sections-ice --dir nested

The tool prints the draft and the two entries the repository needs. `--write [--readme-section HEADING]` puts the
finding, its controls and the entries in place. The entries are in `data/findings/index.yaml` and the maintainers'
log, `data/findings/LOG.md` (kept in the maintainers' repository only, not in the public one). An outside
contributor uses `--proposal` instead, which writes to `data/findings/proposed/` with no entries
([CONTRIBUTING.md](../../CONTRIBUTING.md)). The tool finds rows by the program text without
its comments, or by `--id` (the row's program id). `--case` adds the committed rows of a data/vendor/site check case.
When several toolchains fail, `--primary` names the ones the finding is about.

The following parts of the header are generated from the rows.

- The toolchains and modes that fail. These are the ones that share the most common
  `offload.engine.site.matrix.signature`. A compiler that fails another way is named under `other families` and is
  not listed with the others.
- The build line, and the observed message with identifying details scrubbed.
- The identical-signature count.
- The expected output, taken from a passing row.
- The gate's four environments, and whether (c) ran on another node or GPU.
- The other families that ran the file correctly.
- Each control's result. A control is claimed only on the compilers where a row passes. The tool's notes name the
  others, and the sentence leaves them out.

## What is left for a person

Each of these is marked `TODO(human)`:

| marker | what to write |
|---|---|
| `# Finding (...): TODO(human) one-sentence title` | the one-sentence title |
| `- rule: TODO(human) ...` | the specification requirement, cited with version, section, page and lines (`tools/repo/check_citations.py` checks the page and the quote) |
| `- legality: TODO(human) ...` | why the program is legal and who confirmed it. gfortran and `gcc -fopenmp` never count, a compiler under test cannot confirm its own program, and AFAR and upstream LLVM share a front end |
| toolchain names in prose | `tools/repo/check_findings.py` reads which toolchains a clause names (`offload/engine/finding_header.py mentions`, using `catalog/toolchains.yaml`). A family name alone means every release ("CCE fails"). A version names that release ("CCE 21.0.4", "NVHPC 25.11"). A major version names the first release of that line, so "CCE 21" is 21.0.3, and an unregistered "NVHPC 25.3" would read as the 25 line, so write the measured version. For GCC, the words near the name pick the install: `A100` or `sm_80` means the A100 build, `MI250X`, `Tioga` or `gfx90a` means the MI250X build, and otherwise both |
| `title:` and `summary:` in the `site:` block | the issue's name in a few words, and a one-sentence summary (no "we", "our", "I") |
| the log row's text | one sentence |

`expected:` is also a `TODO(human)` when no row of the program passes. In that case, write what the output must be
and where that value comes from. If a note says a control's row fails or is missing on a compiler, either record that
row by running the control there or accept that the control does not cover that compiler.

## Check

    python3 -I tools/repo/check_findings.py                # every finding; --summary, --list, FINDING...
    WINGTIP_LANE=<lane> tools/lanes/wingtip_offline.sh tests tests/engine/test_check_findings.py

A draft with an unresolved `TODO(human)` in the file, the README or the index fails
`tools/repo/check_findings.py` and `tests/engine/test_check_findings.py`, so it cannot be committed by accident. The
check (`offload/engine/finding_claims.py`) verifies the following claims.

- Every named control has a recorded passing row on each compiler it is claimed for.
- Every compiler under `other families` that is said to run the file correctly has a recorded passing row.
- The gate ran in all four environments, and (c) is on another node or GPU when the rows name them.
- The counts match the rows. These are `N of M cells reproduce ...`, `identical signature on N of M failing cells`,
  and `N confirmed` for a campaign's gate rows.
- "The same way" means one signature.

The check has two modes. `committed` reads only the committed check rows and skips what only `results/` could decide,
so it runs anywhere, including wingtip lanes. `full` needs `results/` (that is, Tuolumne) and also reads the campaign
rows that the header names (`results/...jsonl`). Write those paths in the header, as the tool does.
`COMPLIANT_FINDINGS_MODE` forces one mode.

## The baseline

`catalog/findings_claims_baseline.yaml` lists the claims that older findings made without rows. It is a ratchet. A
violation outside the list fails, and so does an entry that no longer holds (delete it), so the list only shrinks. Do
not add a new finding's claims to it. Record the rows instead. Regenerate the list only to remove fixed entries, with
`python3 -I tools/repo/check_findings.py --write-baseline` on Tuolumne, and review the diff to confirm that it only
loses entries.

## The site: block

A finding file may end with an optional block of comment lines that the public issue site
 shows when present; everything else on
the site is generated. Keys, one per line between `site:` and `end site` (`!` in Fortran, `//` in C):
`title`, `summary`, `workaround`, `found_in`, `control` (repeatable: a path relative to findings and a
one-line description), `report`, `same_as` (another finding id: the same defect), `disposition`
(`not-a-compiler-issue <reason>` and `out-of-scope <reason>`: never published; `mixed <reason>`: shown as
mixed evidence) and `hide` (`true`: never published). A line starting `+ ` continues the value
above it; no block line may pass 132 characters (Fortran's limit covers comment lines), and the
seed tool wraps them. Unknown keys, longer lines and a `control` path that does not exist fail the build
(offload/engine/site/header.py). The blocks were seeded once from the vendor checks by a
one-off script; data/vendor/checks/dispositions.py now reads the dispositions from them (a
block that does not parse is reported and skipped there, so the vendor tools still load; the site build
fails on it). A seeded title that starts with a driver name (`ftn: `, `amdflang -fopenmp-version=60: `)
is shown without it when the issue fails on more than one compiler family.
