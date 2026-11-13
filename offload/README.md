# offload

The installed Python package behind the `offload` command. It answers two questions about OpenMP and OpenACC device offload: what a compiler does with a construct, and what the known problems are.

    python -m offload COMMAND [ARGS]     # or the installed `offload`

| Module | Command | Does |
| --- | --- | --- |
| `cli.py`, `__main__.py` | `offload` | Checks the data, then dispatches to a subcommand. |
| `canuse.py` | `offload can-use QUERY` | Lists the compilers and versions that support a clause, directive or construct. |
| `issues.py` | `offload issues [QUERY]` | Searches the known problems and shows one with its reproducer. |
| `data.py` | | Locates the site data (`issues.json`, `canuse/`) that `can-use` and `issues` read. |
| `_bundle.py` | | Copies the catalog, findings and site data into an installed package at build time. |

`data.py` reads the data from the install bundle or from `OFFLOAD_DATA`. In a checkout it reads a cache (`.offload-cache/`) that is built on first use and rebuilt when the findings or catalog change.

`engine/` holds everything else: the program generators, fuzzers, confirmer, result reports and the site build. `engine/README.md` is the place to start.
