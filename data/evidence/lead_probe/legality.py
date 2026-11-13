#!/usr/bin/env python3
"""Rerun offload.engine.prerun.check (offload.engine.rules with the race
rule and the restriction checks, plus the AFAR flang/clang front end) on
every finding source under data/findings/, for the legality lines of the
finding headers (the old fuzz headers named gfortran -std=f2008 and AFAR's
own front end; the widened-catalog drafts named gfortran / gcc
-fsyntax-only). Runs on a compute node (the front end compiles).

    python3 -I data/evidence/lead_probe/legality.py OUT.jsonl [FILE ...]
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from offload.engine import prerun  # noqa: E402


def version_of(text: str, path: Path) -> int:
    m = re.search(r"version (\d\d)\b", text[:3000])
    if m:
        return int(m.group(1))
    m = re.search(r"OpenMP (\d)\.(\d)", text[:3000])
    if m and f"{m.group(1)}{m.group(2)}" in ("45", "50", "51", "52", "60"):
        return int(m.group(1) + m.group(2))
    return 52


def main():
    out = Path(sys.argv[1])
    files = [Path(f).resolve() for f in sys.argv[2:]] or sorted(
        p for p in (ROOT / "data" / "findings").rglob("*")
        if p.suffix in (".f90", ".c") and "controls" not in p.parts)
    with out.open("w") as fh:
        for p in files:
            text = p.read_text(errors="replace")
            lang = "c" if p.suffix == ".c" else "f90"
            v = version_of(text, p)
            t0 = time.time()
            r_ok, r_why = prerun.rules_witness((text, lang, None, v))
            # the front end's limit: two findings are front-end hangs
            f_ok, f_why = prerun.frontend_witness((text, lang, None, v),
                                                  timeout_s=120)
            # the verdict is offload.engine.prerun.check's own
            ok, why = prerun.check((text, lang, None, v), timeout_s=120)
            rec = {"file": str(p.relative_to(ROOT)), "lang": lang,
                   "version": v, "model": prerun._model_of(text),
                   "rules": r_ok, "rules_reasons": r_why,
                   "frontend": f_ok, "frontend_reasons": f_why,
                   "ok": ok, "reasons": why,
                   "kind": None if ok else prerun.refusal_kind(why),
                   "seconds": round(time.time() - t0, 1)}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(rec["file"], ok, rec["kind"], flush=True)


if __name__ == "__main__":
    main()
