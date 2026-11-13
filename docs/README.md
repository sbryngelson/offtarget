# Documentation

Read in this order. Paths are relative to this folder.

## Using the tool

1. [usage](usage.md) lists every option of `offload can-use` and `issues`.
2. [scope](scope.md) says what a result does and does not tell you, and where the catalog stops.

## Understanding the catalog

3. [how-it-works](how-it-works.md) explains how a finding is established and how the can-use tables are built.
4. [upstream](upstream.md) lists problems found in the upstream test suites and where each has been filed.
5. [tooling/confirm](tooling/confirm.md) describes how failures become verdicts, deduplicated findings and drafts.
6. [tooling/expected-behaviour](tooling/expected-behaviour.md) says where a program's expected value comes from.
7. [tooling/nested-data](tooling/nested-data.md) describes the generator for nested pointer and aggregate programs.

## Working on the repository

8. [maintainers](maintainers.md) covers the layout, adding a finding, regenerating, testing and publishing.
9. [tooling/setup](tooling/setup.md) lists the git-ignored inputs a clone needs and how to get them.
10. [tooling/contributing](tooling/contributing.md) has the standing rules and the steps for adding a finding, a compiler or a campaign. The linter and its tooling are kept on the `linter` branch.
11. [tooling/regenerate](tooling/regenerate.md) lists every generated file with its inputs and how to check that it is current.
12. [tooling/site](tooling/site.md) explains how the website is built from the findings.
13. [tooling/publishing](tooling/publishing.md) explains how the site is deployed and the package is released.

## The maintainers' own machines

These pages describe how the maintainers run the measurements and the full test suite on their own machines. They
serve as an example of a setup and are not needed to use or extend the tool.

- [tooling/wingtip](tooling/wingtip.md) covers the A100 host, its resource cap, and the offline and Tioga test lanes.
- [tooling/dashboard-publish](tooling/dashboard-publish.md) covers the private dashboard.

## Generated reference

These pages are generated, so do not edit them: [tooling/toolchains](tooling/toolchains.md), [tooling/omp5-vs-52](tooling/omp5-vs-52.md), [tooling/omp-50-vs-52-results](tooling/omp-50-vs-52-results.md).
