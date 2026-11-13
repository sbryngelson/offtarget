# Publishing the dashboard

The dashboard is a standalone artifact. It is one HTML page plus plain JSON data files, and any
claude.ai account can publish it with one Artifact call. It does not use the Dashboard artifact
type, ArtifactData documents or account-bound assets.

## Publish

1. Build the datasets from `results/`:

       python3 -I tools/site/dashboard_data.py results/dash

   This writes one `<id>.json` per dataset and prints the row count of each.

   | datasets | content |
   |---|---|
   | `atoms`, `programs` | OpenMP support rows and program sources |
   | `runs`, `runs_x0`, `runs_g90`, `runs_nvhpc` | runs by memory mode and target |
   | `ompvv`, `ompvv_nvhpc` | the OpenMP Validation and Verification suite |
   | `fuzz`, `fuzz_sources`, `stress` | fuzz campaigns and stress results |
   | `acc_atoms`, `acc_programs`, `acc_runs` | OpenACC |

2. Build the page:

       python3 -I tools/site/dashboard_standalone.py results/dash results/dash_standalone

   This writes three things:

   - `index.html`, which is `tools/site/dashboard_page.html` with its own light and dark theme
     tokens and a small `dash` runtime that fetches `data/<id>.json` next to the page.
   - `data/*.json`.
   - `files.json`, the `files` map of the publish call.

   It stops when a file exceeds 16 MB or the set exceeds 64 MB.

3. Check it:

       python3 -I tools/site/dashboard_render_check.py --standalone results/dash_standalone

   The check serves the directory over local HTTP and loads the page in headless Chrome at 1280
   and 420 px. It clicks every control and the first rows of every table. It fails on any error, a
   dataset that does not load, a blank headline mark or sideways scroll, and it must report 0
   problems. It needs node 22 or newer and `google-chrome` or `chromium` on `PATH`. On Tuolumne,
   run it on a compute node as described in [site.md](site.md), "Check".

4. Publish the page with the Artifact `publish` action. Set `file_path` to
   `results/dash_standalone/index.html` and `files` to the contents of `files.json`. The first
   publish gives a new URL. To update the artifact, pass that URL as `url`; the account must own
   the artifact or have edit access. The artifact stays private until it is shared from the
   page's Share menu.

## Editing the page

Edit `tools/site/dashboard_page.html`. Every table declares its columns once, in
`COLS.<table id>`, and its `<th data-field>` row must have one header per configured column.
Then run

    python3 -I -m pytest -q tests/site/test_site_web.py tests/site/test_site_web.py

and repeat steps 2 to 4. Run without `--standalone`,
`python3 -I tools/site/dashboard_render_check.py DIR` renders the page from the datasets in
`DIR`, using a stand-in for the Dashboard type's `dash` API.
