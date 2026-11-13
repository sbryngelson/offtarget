# tools/site

These scripts build the public website and the dashboard page, and check both before publishing. `tools/site_publish.sh OUT_DIR` does it all in one command. The procedures are in [site](../../docs/tooling/site.md), [publishing](../../docs/tooling/publishing.md) and [dashboard-publish](../../docs/tooling/dashboard-publish.md).

| file | role |
|---|---|
| `site_build.py` | build the site into `OUT` |
| `site_check.py` | check a built site: links, leaks of user, host or private paths |
| `site_check.mjs` | headless Chrome half of `site_check.py` (clicks filters and sorts, reports errors) |
| `site_inputs.py` | write or check the committed inputs in `site/inputs/` |
| `site_requirements.txt` | pinned Python packages for the build, check and tests |
| `dashboard_data.py` | datasets of the dashboard from the results |
| `dashboard_page.html` | the dashboard page |
| `dashboard_standalone.py` | dashboard with data embedded, publishable by any account |
| `dashboard_render_check.py` | render the dashboard headless before publishing |
| `dashboard_render_check.mjs` | headless Chrome half of the render check |
