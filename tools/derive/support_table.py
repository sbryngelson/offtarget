"""Write the support table (results/support_table.md and .csv).

    python3 -I tools/derive/support_table.py [--results results/matrix.jsonl]
        [--claims catalog/omp/claims.yaml] [--baseline results/baseline.jsonl]
        [--model acc] [--lang c]

Reads the matrix, the committed oracle audit summary and the claims, and
prints the cell count and the number of claim mismatches. Every CSV ends with
a `lang` column. The other modes read acc_matrix.jsonl and
tests/data/acc_audit_summary.json (``--model acc``), matrix_c.jsonl,
baseline_c.jsonl and tests/data/oracle_audit_summary_c.json (``--lang c``), or
acc_matrix_c.jsonl (NVHPC 25.11 and 26.9 rows) and
tests/data/acc_audit_summary_nvhpc*_c.json (both). Each writes
results/{acc_,}support_table{_c,}.md and .csv, and copies in data/reports/.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import report  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", choices=("omp", "acc"), default="omp")
    ap.add_argument("--lang", choices=("f90", "c"), default="f90")
    ap.add_argument("--results", type=Path, default=None)
    ap.add_argument("--claims", type=Path, default=None)
    ap.add_argument("--audit", type=Path, default=None)
    ap.add_argument("--baseline", type=Path, default=None)
    a = ap.parse_args(argv)
    acc = a.model == "acc"
    c = a.lang == "c"
    accc = acc and c  # OpenACC C (NVHPC)
    a.results = a.results or (report.ACC_C_MATRIX if accc else
                              report.ACC_MATRIX if acc else
                              report.C_MATRIX if c else report.MATRIX)
    a.claims = a.claims or (report.ACC_CLAIMS if acc else report.CLAIMS)
    a.audit = a.audit or (report.ACC_C_AUDIT if accc else
                          report.ACC_AUDIT if acc else
                          report.C_AUDIT if c else report.AUDIT)
    a.baseline = a.baseline or (ROOT / "results" / "no_acc_baseline.jsonl"
                                if acc else report.C_BASELINE if c
                                else report.BASELINE)
    out_md = out_csv = None
    if accc:
        out_md = a.results.with_name("acc_support_table_c.md")
        out_csv = a.results.with_name("acc_support_table_c.csv")
    elif acc:
        out_md = a.results.with_name("acc_support_table.md")
        out_csv = a.results.with_name("acc_support_table.csv")
    elif c:
        out_md = a.results.with_name("support_table_c.md")
        out_csv = a.results.with_name("support_table_c.csv")
    table, mism = report.write_report(a.results, a.claims, a.audit,
                                      a.baseline, out_md, out_csv)
    if accc:
        docs = ROOT / "data" / "reports"
        (docs / "acc-c-support-table.md").write_text(
            out_md.read_text().replace("](../", "](../../"))
        (docs / "acc_c_support_table.csv").write_text(out_csv.read_text())
    elif acc:
        docs = ROOT / "data" / "reports"
        (docs / "acc-support-table.md").write_text(
            out_md.read_text().replace("](../", "](../../"))
        (docs / "acc_support_table.csv").write_text(out_csv.read_text())
    elif c:
        docs = ROOT / "data" / "reports"
        (docs / "c-support-table.md").write_text(
            out_md.read_text().replace("](../", "](../../"))
        (docs / "c_support_table.csv").write_text(out_csv.read_text())
    unaud = sum(m.oracle_unaudited for m in mism)
    print(f"{len(table)} cells; {len(mism)} claim mismatches "
          f"({unaud} on oracle-unaudited atoms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
