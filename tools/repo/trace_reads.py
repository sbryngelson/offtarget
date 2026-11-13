#!/usr/bin/env python3
"""List the repository files a command opens.

    python3 -I tools/repo/trace_reads.py offload/__main__.py COMMAND ARGS...

Runs the script in-process with an audit hook on open() and prints "=== reads ===" and then the
repository-relative paths it read, one per line. Used to build tools/repo/bundle_manifest.txt.
"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
seen = set()


def hook(event, args):
    if event == "open" and isinstance(args[0], str):
        try:
            p = Path(args[0]).resolve()
        except OSError:
            return
        if p.is_file() and ROOT in p.parents:
            seen.add(str(p.relative_to(ROOT)))


def main(argv) -> int:
    script, *rest = argv
    sys.path.insert(0, str(ROOT))
    sys.addaudithook(hook)
    sys.argv = [script, *rest]
    try:
        runpy.run_path(str(ROOT / script), run_name="__main__")
    except SystemExit:
        pass
    print("\n=== reads ===")
    print("\n".join(sorted(seen)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
