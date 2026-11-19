#!/usr/bin/env python3
"""Link the maintainers' private checkout into this tree (tools/repo/private.yaml).

    python3 -I tools/repo/link_private.py            # make or repair the links
    python3 -I tools/repo/link_private.py --check    # list what is missing; exit 1 if anything is
    python3 -I tools/repo/link_private.py files [-z] # every file of the tree with the linked ones (for the lanes)

The checkout is the `root` of `private.yaml` in your local settings. Without it there is nothing to link. The file
list follows the links that are there.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from offload.engine import private as P  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", choices=["link", "files"], default="link")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("-z", action="store_true", help="separate the file list with NUL")
    a = ap.parse_args(argv)
    priv = P.root()
    if priv is not None and not (priv / ".git").exists():
        sys.exit(f"private.yaml root {priv} is not a git checkout")
    if a.what == "files":
        sep = "\0" if a.z else "\n"
        sys.stdout.write("".join(f + sep for f in P.files()))
        return 0
    if priv is None:
        print("no private checkout is set (private.yaml: root in your local settings); nothing to link")
        return 0
    try:
        todo = P.link(priv, P.ROOT, P.patterns(), check=a.check)
    except P.PrivateError as e:
        sys.exit(str(e))
    for t in todo:
        print(("missing: " if a.check else "linked: ") + t)
    return 1 if a.check and todo else 0


if __name__ == "__main__":
    sys.exit(main())
