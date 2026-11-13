#!/bin/bash
# Build the public offload-issue site from committed data and check it: the one command
# a person, or the GitHub Actions workflow (.github/workflows/site.yml), runs before the
# site is published (docs/tooling/publishing.md).
#
#   tools/site_publish.sh OUT_DIR [--repo-url URL]
#
# OUT_DIR must not exist yet, or be empty: a file left from an earlier build would be
# published with the rest. Then tools/site/site_build.py writes the pages into it and
# tools/site/site_check.py checks them: every in-site link resolves, no file holds a user name,
# host name or private path, and in headless Chrome at 1280 and 420 px every kind of page
# loads with no script error, no sideways scroll and a non-empty main region, with every
# filter and sort control of the issue list clicked and compared with the data.
#
# Needs: python3 >= 3.10 with PyYAML (tools/site/site_requirements.txt), node >= 22 (the check's
# browser driver, tools/site/site_check.mjs, uses node's own fetch and WebSocket) and Google
# Chrome or Chromium (google-chrome, chromium or chromium-browser on PATH). Without node or
# the browser this script stops before building: a check without the browser is not the
# check the site needs. The build reads committed data only: the finding files, the finding
# matrix under data/vendor/checks, and site/inputs/ (tools/site/site_inputs.py), nothing from the
# git-ignored measurements, so it runs the same in a clean clone (offload.engine.site.inputs
# MANIFEST). Exit 0 only when the check reports 0 problems; 1 otherwise; 2 on usage.
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

usage() { echo "usage: $0 OUT_DIR [--repo-url URL]" >&2; exit 2; }
[ $# -ge 1 ] || usage
case "$1" in -*) usage ;; esac
out=$1
shift

if [ -e "$out" ] && [ -n "$(ls -A "$out")" ]; then
  echo "site_publish: $out exists and is not empty; build into a new or empty directory" >&2
  exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo "site_publish: node >= 22 is needed for the browser check (tools/site/site_check.mjs)" >&2
  exit 1
fi
major=$(node -p 'process.versions.node.split(".")[0]')
if [ "$major" -lt 22 ]; then
  echo "site_publish: node >= 22 is needed (found $(node --version))" >&2
  exit 1
fi
chrome=$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)
if [ -z "$chrome" ]; then
  echo "site_publish: Google Chrome or Chromium is needed for the browser check" \
       "(google-chrome, chromium or chromium-browser on PATH)" >&2
  exit 1
fi
echo "site_publish: node $(node --version), browser $chrome"

python3 -I tools/site/site_build.py "$out" "$@"
check_args=()
prev=""
for a in "$@"; do
  if [ "$prev" = "--repo-url" ]; then check_args=(--repo-url "$a"); fi
  prev=$a
done
python3 -I tools/site/site_check.py "$out" ${check_args[@]+"${check_args[@]}"}
echo "site_publish: $out: $(find "$out" -type f | wc -l) files, checked"
