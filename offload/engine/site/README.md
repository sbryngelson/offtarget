# offload/engine/site

This package builds the data of the public site. It turns the findings and the vendor-check results into the JSON that the site pages and the `offload issues` and `offload can-use` commands read.

`tools/site/site_build.py` builds the site, and `site.data.build` returns the data in code. `docs/tooling/site.md` and `docs/tooling/publishing.md` give the publishing steps.

It reads `data/findings/`, `data/vendor/checks/`, `catalog/toolchains.yaml`, `catalog/machines.yaml` and `site/inputs/`. The files in `site/inputs/` are committed compact copies of the git-ignored measurements, so a clean clone builds the same site. It writes the JSON data (`issues.json`, `canuse/`, `search.json`, `compilers`).

- `data.py` chooses which findings are published, groups them into defects and produces the JSON for each page.
- `matrix.py` what each finding's program does on every toolchain, GPU and memory mode.
- `columns.py` rows, columns and names of the feature-support table.
- `header.py` the optional `site:` block of a finding file.
- `inputs.py` the committed inputs.
- `scrub.py` removes user names, host names and private paths from public text and finds leaks.

Read `data.py` first.
