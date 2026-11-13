# Publishing the site

This page describes how the site ([site.md](site.md)) is built and deployed to GitHub Pages, by
GitHub Actions or by hand. It also covers what a maintainer switches on and which decisions stay
manual. The workflow deploys nothing until the repository variable `SITE_PUBLISH` is `true`.

## Pieces

| piece | role |
|---|---|
| `site/inputs/` | committed copies of what the build needs from git-ignored measurements: `atoms.json.gz` (feature support) and `citations.json` (verified specification citations of every published finding). `python3 -I tools/site/site_inputs.py` writes them, and `python3 -I tools/regenerate.py --check site-inputs` reports when they are stale |
| `tools/site_publish.sh OUT_DIR [--repo-url URL] [--source-branch NAME]` | builds the site into `OUT_DIR` from committed data, then runs `tools/site/site_check.py`. It exits 0 only with 0 problems, 1 on a failure or a non-empty `OUT_DIR`, and 2 on a usage error |
| `.github/workflows/site.yml` | runs on every push to `master` and on manual dispatch. It installs Python 3.13 with PyYAML and pytest (`tools/site/site_requirements.txt`) and node 22, runs `site_publish.sh _site` with the repository URL and default branch, runs `tests/site`, uploads `_site`, and deploys it if the switch is on |
| `tests/site/test_site_workflow.py`, `tests/site/test_site_inputs.py` | check that the workflow names only existing paths, runs only CPU commands, reads nothing git-ignored, pins every action to a commit, holds no secret and asks for the least permissions, and that the committed inputs are tracked and current |

The build reads only the files in `MANIFEST` (`offload/engine/site/inputs.py`), so a clone of the
repository is enough. A build in a clean clone gives the same site as a build in a tree that has
`results/`.

### Chrome and node

`site_check.py` drives headless Chrome through `tools/site/site_check.mjs`, which uses node's own
`fetch` and `WebSocket`. It needs node 22 or newer and `google-chrome`, `chromium` or
`chromium-browser` on `PATH`. `site_publish.sh` stops before building when either is missing.
The GitHub `ubuntu-24.04` runner image ships Chrome, and the workflow installs node 22. On
Tuolumne, run the check on a compute node ([site.md](site.md), "Check"). wingtip has no Chrome.

## Turning it on

1. Push the repository to GitHub with `master` as the default branch. If it is named otherwise,
   change `branches:` in `site.yml`.
2. Under **Settings > Pages > Build and deployment > Source**, choose **GitHub Actions**, not
   "Deploy from a branch". The `github-pages` environment is created on the first run.
3. Under **Settings > Actions > General**, enable Actions. "Workflow permissions" may stay at
   **Read repository contents**, because the deploy job declares the `pages` and `id-token`
   permissions itself. The workflow uses no secret and no personal token.
4. Run the workflow once by hand without deploying, with **Actions > site > Run workflow**. The
   `deploy` job is skipped because the switch is not set. In the `build` job log, check the
   browser line (`google-chrome --version`), that `site_publish` ends in `... files, checked` with
   `0 problems`, and that the tests pass. The pages are the run's `github-pages` artifact.
5. Set the switch. The `deploy` job runs only when `vars.SITE_PUBLISH == 'true'`. In the browser,
   go to **Settings > Secrets and variables > Actions > Variables > New repository variable** and
   add `SITE_PUBLISH` with the value `true`. With the GitHub CLI, run:

       gh variable set SITE_PUBLISH --body true --repo OWNER/REPOSITORY
       gh variable list --repo OWNER/REPOSITORY

   Run the workflow again by hand. The `deploy` job prints the page URL,
   `https://<owner>.github.io/<repository>/`.
6. Open the page and look at the issue list, one issue page, one compiler page, feature support
   and the method page.

From then on, every push to `master` rebuilds, checks and redeploys the site while the switch is
`true`. If the build or check of a push fails, nothing is deployed and the previous deployment
stays up. With the switch off (`false`, or the variable deleted), every push still builds and
checks the site but deploys nothing.

### A dry run on a private repository

The workflow runs on a private repository. GitHub Pages is available there with Pro, Team or
Enterprise, and the published page is public on github.io even though the repository is private.
The `build` job alone makes a dry run that exposes nothing. Leave `SITE_PUBLISH` unset, so the
`deploy` job is skipped whether or not Pages is enabled. Run the workflow by hand and download
the `github-pages` artifact from the run's summary. Enable Pages and set the switch only when the
site is meant to be seen.

### Rollback

- To undo a bad page that is already deployed, run `git revert` on the commit on `master` and
  push. Alternatively, pick the last good run under **Actions > site** and choose **Re-run all
  jobs**, which rebuilds that run's commit and redeploys it.
- To stop publishing, run `gh variable set SITE_PUBLISH --body false --repo OWNER/REPOSITORY` or
  `gh variable delete SITE_PUBLISH --repo OWNER/REPOSITORY`, or edit the variable under
  **Settings > Secrets and variables > Actions > Variables**. Later pushes build and check but
  deploy nothing, and the deployed page stays up.
- To take the site down, use **Settings > Pages > Unpublish site** or set Source back to "None".
  If the switch is still on, `deploy` fails on the next push until Pages is enabled again, so turn
  the switch off as well. **Actions > site > ... > Disable workflow** stops the runs.
- A bad build that never deployed needs no rollback, because the previous deployment is still up.
  Fix the cause named in the `build` log and push.

### Updating the pinned actions

Every `uses:` in `site.yml` is pinned to a full commit SHA, with the release tag in a comment. To
move one, find the tag's commit and change both the SHA and the comment:

    git ls-remote --tags https://github.com/actions/checkout

For a lightweight tag, the SHA on the tag's own line is the commit. For an annotated tag, the
commit is on the line marked `^{}`, and the other line is the tag object, which `uses:` does not
accept. All pinned tags in `site.yml` are lightweight. `tests/site/test_site_workflow.py` fails on
a tag or branch reference.

## Preview

The private preview is the `OUT_DIR` that `site_publish.sh` produced, published as a claude.ai
artifact. `index.html` is the page and every other file goes through the `files` map
([contributing.md](contributing.md), section 3.6, describes this). Only its owner and the people
they share it with can see it, and it is useful for looking at a branch's build. The public site is
the same pages, built by the workflow from `master`. The only difference in content comes from
`--repo-url`. The workflow passes the repository URL, so issue pages link to their source files,
and a preview built without it has no such links.

## Decisions made by hand

Nothing in the repository does these steps.

- **Going public.** Making the repository public and enabling Pages are actions in GitHub's
  settings.
- **The licence.** The repository's `LICENSE` is MIT. The site's "Sources and credits" section
  names what the programs derive from: the OpenMP Validation and Verification suite, the LLVM
  project's offload tests (Apache 2.0 with LLVM exception) and AMD's AOMP tests. Each is credited
  in its program's header. Check the licence of the catalog, the findings and the site text
  against those sources' terms.
- **The whole repository.** The public repository is not this one.
  `tools/repo/public_export.py` builds it as one commit from the tracked files and leaves out
  what `tools/repo/public_exclude.txt` names. That covers the vendor report drafts and their
  texts, and the benchmark sets. The benchmark code comes from other projects under their own
  licences, and the held-out sets stay sealed. The export's `data/bench/` holds a README and
  the programs that findings name. The export scrubs the generated reports and refuses to run
  when private text is left. Its copy has its own `THIRD_PARTY_NOTICES.md` for what is published,
  and a README for each directory it trims.
- **Specification quotations.** The site quotes the OpenMP (4.5 to 6.0) and OpenACC (3.4)
  specifications from `site/inputs/citations.json`, and attributes each quote to its version,
  section and page. The OpenMP documents' notice reads: "Copyright © 1997-20xx OpenMP Architecture Review
  Board. Permission to copy without fee all or part of this material is granted, provided the
  OpenMP Architecture Review Board copyright notice and the title of this document appear.
  Notice is given that copying is by permission of the OpenMP Architecture Review Board." The
  "Quoted specification text" notices on the Method page satisfy it
  (`tests/site/test_site.py::test_method_page_carries_the_specification_notices`). The
  OpenACC 3.4 notice grants no such permission: "© 2011-2025 OpenACC-Standard.org.
  All rights reserved. Complying with all applicable copyright laws is the responsibility of the user.
  Without limiting the rights under copyright, no part of this document may be reproduced,
  stored in, or introduced into a retrieval system, or transmitted in any form or by any means
  (electronic, mechanical, photocopying, recording, or otherwise), or for any purpose, without
  the express written permission of the authors." The Method page shows this notice too. Decide
  whether the short attributed OpenACC passages may stay, need permission from
  OpenACC-Standard.org, or become section references without quoted text.
- **Git history.** The history holds files that were removed later (drafts, logs, one-off
  scripts) and the private paths and user names that the build scrubs from everything it
  publishes. Before the first push, decide whether to publish the full history, squash it, or
  rewrite it (`git filter-repo`). The site build and its checks look only at the current tree.
- **Vendor report drafts** (`data/vendor/{amd,hpe,nvidia}`). These are not part of the site, and
  they are sent by hand, if at all.

# Releasing the package

`.github/workflows/release.yml` builds `offtarget` and uploads it to PyPI by Trusted Publishing, with no stored
token. It runs only on a pushed `v*` tag or a manual dispatch, never on a push to a branch.

| piece | role |
|---|---|
| `pyproject.toml` | the version is the tag (`v0.2.0` gives `0.2.0`), read by hatch-vcs; an untagged build is `X.Y.Z.devN`. The sdist's include list names what the build hook reads and nothing else |
| `hatch_build.py` | puts the data an installed `offload` reads into the wheel (`offload/_bundle.py`) |
| `tests/test_offload.py` | builds the wheel and the sdist, builds a second wheel from the sdist alone, and checks that the two match, that the sdist holds no drafts, sealed-set lists or tests, and that the installed command works |
| `release.yml` | builds the sdist and the wheel from it, runs `twine check --strict`, installs the wheel and checks that `offload --version` matches the tag, then uploads |

## Turning it on

1. On https://pypi.org/manage/account/publishing/, add a pending publisher: project `offtarget`, this repository's
   GitHub account and name, workflow `release.yml`, environment `pypi`. On https://test.pypi.org, the same
   with environment `testpypi`.
2. Under **Settings > Environments**, the `pypi` and `testpypi` environments are created on the first run. A
   required reviewer on `pypi` makes every upload wait for approval.
3. Dry run: **Actions > release > Run workflow**, target `testpypi`. The version is a `.devN` one.
4. Release: `git tag v0.1.0 && git push origin v0.1.0`. A version can be uploaded once; a fix needs a new tag.

The installed data is the findings at the tagged commit. A release after findings change gives `pip install -U
offtarget` users the new catalog.
