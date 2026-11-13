"""offload can-use: which compilers and versions support a clause, directive or construct."""
import argparse
import difflib
import json
import sys

from offload import data

WORDS = ("correct", "incorrect", "unsupported", "unknown")


def lookup(query: str) -> list[str]:
    """Feature ids for a query: the exact id, else every id containing it (case-insensitive)."""
    ids = data.load("canuse/index.json")
    if query in ids:
        return [query]
    q = query.lower()
    return [i for i in ids if q in i.lower()]


def grid(row: dict) -> dict[str, dict[str, str]]:
    """{compiler label: {target name: state or '-'}} for one catalog program's row."""
    cols = data.load("canuse/columns.json")
    shorts = [(t, n, kind) for kind, ts in cols["targets"].items() for t, n in ts]
    out = {}
    for tc, label in cols["rows"]:
        ran = cols["runs"][tc]
        out[label] = {n: (row["cells"].get(f"{tc}|{t}", {}).get("state", "unknown") if t in ran else "-")
                      for t, n, k in shorts}
    return out


def _table(row: dict) -> str:
    g = grid(row)
    targets = list(next(iter(g.values())))
    w0 = max(len(l) for l in g) + 2
    ws = [max(len(t), 11) + 2 for t in targets]
    lines = [" " * w0 + "".join(t.ljust(w) for t, w in zip(targets, ws)).rstrip()]
    lines += [(label.ljust(w0) + "".join(c.ljust(w) for c, w in zip(cells.values(), ws))).rstrip()
              for label, cells in g.items()]
    return "\n".join(lines)


def render(feature_id: str, fmt: str = "text") -> str:
    rows = data.load(f"canuse/{feature_id[0]}.json").get(feature_id, [])
    if fmt == "json":
        return json.dumps(rows, indent=1)
    out = []
    for row in rows:
        model = "OpenACC" if row.get("model") == "acc" else "OpenMP"
        lang = "C" if row.get("lang") == "c" else "Fortran"
        head = f"{feature_id}   {model} {row.get('version', '')}, {lang}"
        parts = [head]
        if row.get("citation"):
            parts.append(row["citation"])
        parts += ["", _table(row)]
        for i in row.get("issues", ()):
            parts.append(f"\nknown issue: {i['title']}  (offload issues {i['page']})")
        out.append("\n".join(parts))
    return "\n\n".join(out) + "\n" if out else f"{feature_id}: no catalog program\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="offload can-use",
                                 description="which compilers and versions support a clause, directive or construct")
    ap.add_argument("feature", nargs="?", help="a feature id or part of one, e.g. omp.clause.map.present or map.present")
    ap.add_argument("--list", action="store_true", help="list the feature ids (those containing FEATURE, if given)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    a = ap.parse_args(argv)
    ids = data.load("canuse/index.json")
    if a.list:
        shown = lookup(a.feature) if a.feature else ids
        print("\n".join(shown))
        return 0 if shown else 1
    if not a.feature:
        ap.error("give a feature, or --list")
    hits = lookup(a.feature)
    if len(hits) == 1:
        print(render(hits[0], a.format), end="")
        return 0
    if hits:
        print("\n".join(hits))
        print(f"offload can-use: '{a.feature}' matches {len(hits)} features; name one", file=sys.stderr)
        return 1
    near = difflib.get_close_matches(a.feature, ids, n=3, cutoff=0.6)
    print(f"offload can-use: no feature '{a.feature}'" + (f"; did you mean {', '.join(near)}?" if near else ""),
          file=sys.stderr)
    return 1
