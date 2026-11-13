"""Build the OpenMP catalog skeleton from an llvm-tblgen JSON dump."""
import json
import sys
from pathlib import Path

import yaml

from offload.engine.catalog import Skeleton, load_skeleton  # noqa: F401

UNBOUNDED = 2147483647
LANGS = {"L_C": "C", "L_Fortran": "Fortran"}


def _ver(v: int) -> int | None:
    return None if v == UNBOUNDED else v


def merge_rule(old: dict | None, new: dict) -> dict:
    """Merge two rules for the same clause on one directive.

    Stronger information wins: once and exclusive_group survive from either
    side, and the version range is the narrowest of the two (max of mins,
    min of maxes). Commutative, so list order does not matter.
    """
    if old is None:
        return dict(new)
    maxes = [v for v in (old["max_ver"], new["max_ver"]) if v is not None]
    return {
        "min_ver": max(old["min_ver"], new["min_ver"]),
        "max_ver": min(maxes) if maxes else None,
        "once": old["once"] or new["once"],
        "exclusive_group": old["exclusive_group"] or new["exclusive_group"],
    }


def build_skeleton(seed_json: Path) -> dict:
    db = json.loads(Path(seed_json).read_text())

    def spellings(rec: dict) -> list[dict]:
        return [{"text": db[s["def"]]["spelling"],
                 "min_ver": db[s["def"]]["minVersion"],
                 "max_ver": _ver(db[s["def"]]["maxVersion"])}
                for s in rec["spellings"]]

    def kind(rec: dict, base: str) -> bool:
        return base in rec.get("!superclasses", [])

    clause_spell = {k: spellings(v)[0]["text"] for k, v in db.items()
                    if isinstance(v, dict) and kind(v, "Clause")}
    # `default` and `update` each name two clause records; the one whose
    # record name matches the spelling keeps it, the other is qualified.
    clause_names = {}
    for k, n in clause_spell.items():
        base = k.removeprefix("OMPC_")
        dup = list(clause_spell.values()).count(n) > 1
        clause_names[k] = (f"{n} ({base})"
                           if dup and base.lower().replace("_", "") != n
                           .replace("_", "") else n)
    dir_names = {k: spellings(v)[0]["text"] for k, v in db.items()
                 if isinstance(v, dict) and kind(v, "Directive")}
    # Two records may share a spelling (the block and standalone `ordered`);
    # key those by "<spelling> (<association>)" so every record is kept.
    counts = {n: list(dir_names.values()).count(n) for n in dir_names.values()}
    dir_keys = {k: n if counts[n] == 1 else
                f"{n} ({db[k]['association']['def'].removeprefix('AS_')})"
                for k, n in dir_names.items()}

    clauses = {clause_names[k]: {"spellings": spellings(db[k])}
               for k in clause_names}

    directives = {}
    for key in dir_names:
        rec = db[key]
        allowed = {}

        def add(field: str, once: bool, group: str | None = None,
                only_new: bool = False):
            for ref in rec[field]:
                vc = db[ref["def"]]
                name = clause_names[vc["clause"]["def"]]
                if only_new and name in allowed:
                    continue
                allowed[name] = merge_rule(allowed.get(name), {
                    "min_ver": vc["minVersion"],
                    "max_ver": _ver(vc["maxVersion"]),
                    "once": once,
                    "exclusive_group": group,
                })

        # All exclusive clauses of a directive share the single group name
        # "exclusive": TableGen has no group names.
        # `required` means "at least one of" (flang semantics, e.g. target
        # data: map/use_device_ptr/use_device_addr), not "all of".
        add("allowedClauses", False)
        add("allowedOnceClauses", True)
        add("allowedExclusiveClauses", True, "exclusive")
        # A required clause is also allowed, but only adds an entry when none
        # exists (tile/sizes is both required and once).
        add("requiredClauses", False, only_new=True)
        required = {clause_names[db[r["def"]]["clause"]["def"]]
                    for r in rec["requiredClauses"]}
        directives[dir_keys[key]] = {
            "spellings": spellings(rec),
            "languages": sorted(LANGS[l["def"]] for l in rec["languages"])
            if len(rec["languages"]) < len(LANGS) else [],
            "association": rec["association"]["def"].removeprefix("AS_"),
            "leaves": [dir_keys[l["def"]] for l in rec["leafConstructs"]],
            "allowed": allowed,
            "required": sorted(required),
        }
    return {"directives": directives, "clauses": clauses}


def write_skeleton(seed_json: Path, out: Path) -> None:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(yaml.safe_dump(build_skeleton(seed_json),
                                        sort_keys=True))


if __name__ == "__main__":
    write_skeleton(Path(sys.argv[1]), Path(sys.argv[2]))
