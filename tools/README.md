# tools

Maintainer scripts. Run them as `python3 -I tools/...` from a checkout. Anything that compiles or runs on a GPU needs a compute node (Tuolumne, Tioga) or wingtip. The rest runs anywhere. The commands for users are `offload can-use | issues`, described in [../docs/usage.md](../docs/usage.md). [../docs/maintainers.md](../docs/maintainers.md) gives an overview of the maintainer workflow.

## Entry points

| script | purpose | main command |
|---|---|---|
| `regenerate.py` | rebuild or check every committed generated artifact ([regenerate](../docs/tooling/regenerate.md)) | `python3 -I tools/regenerate.py --check` |
| `campaign.py` | run any registered measurement campaign | `python3 -I tools/campaign.py list` |
| `reduce.py` | reduce a failing program to a minimal reproducer with controls ([contributing](../docs/tooling/contributing.md)) | `python3 -I tools/reduce.py --program FILE --target cce21/1 --name NAME --out DIR` |
| `new_finding.py` | draft a finding file from recorded rows | `python3 -I tools/new_finding.py PROGRAM --campaign NAME --rows FILE...` |
| `confirm.py` | automated bug confirmer ([confirm](../docs/tooling/confirm.md)) | `python3 -I tools/confirm.py case prog.f90 --toolchain cce21` |
| `site_publish.sh` | build and check the public site ([publishing](../docs/tooling/publishing.md)) | `tools/site_publish.sh OUT_DIR` |

## Sub-folders

| folder | holds |
|---|---|
| [lanes/](lanes/README.md) | the wingtip offline lane and the Tioga suite runner |
| [campaigns/](campaigns/README.md) | campaign drivers, corpus harvests, audits, generators |
| [derive/](derive/README.md) | tables and reports derived from results |
| [site/](site/README.md) | website and dashboard build and checks |
| [repo/](repo/README.md) | repository checks, manifests, allowlists |
| [jobs/](jobs/README.md) | cluster job scripts |
| [dataenv/](dataenv/README.md) | data-environment campaign |
| [wild/](wild/README.md) | in-the-wild benchmark scripts |
| [review/](review/README.md) | independent legality reviews of the findings |
