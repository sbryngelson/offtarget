"""kernel-body campaign: the spec rows the generated programs stress.

Each tag names one rule (as offload.engine.nested_cites: version, section,
printed page, margin lines, a verbatim piece of those lines, checked
against results/spec_cache/ by offload.engine.dataenv_rules.check_citation and
tools/repo/check_citations.py). The rules are about what an atomic structured
block may look like and what the construct guarantees across teams, about
the loop iterations that may execute in any order, and about the
statements' data-sharing. The base language's own rules (array
constructors, intrinsic assignment, derived-type components) are not in
the cached texts: a program's legality line says so.
"""
from __future__ import annotations


def _c(version, section, page, lines, quote):
    return {"version": version, "section": section, "page": page,
            "lines": lines, "quote": quote}


M52 = "OpenMP 5.2"

CITES: dict[str, list[dict]] = {
    "omp.atomic.scalar-variables": [
        _c(M52, "4.3.1.3", 79, "22",
           "x, v, d and e (as applicable) are scalar variables of intrinsic type.")],
    "omp.atomic.update-forms": [
        _c(M52, "4.3.1.3", 81, "12-15",
           "x = x operator expr x = expr operator x x = intrinsic-procedure-name (x, expr-list)")],
    "omp.atomic.intrinsics": [
        _c(M52, "4.3.1.3", 79, "25",
           "intrinsic-procedure-name is one of MAX, MIN, IAND, IOR, or IEOR.")],
    "omp.atomic.capture-forms": [
        _c(M52, "4.3.1.3", 83, "1-8",
           "A capture-atomic structured block has one of the following forms: statement capture-statement")],
    "omp.atomic.capture-update-only": [
        _c(M52, "15.8.4", 313, "35-36",
           "an update-capture-atomic structured block must be associated with the construct.")],
    "omp.atomic.write-capture": [
        _c(M52, "4.3.1.3", 83, "9-10",
           "If statement is write-statement as specified above then it is a write-capture-atomic structured block.")],
    "omp.atomic.not-allocatable": [
        _c(M52, "4.3.1.3", 84, "23", "x must not have the ALLOCATABLE attribute.")],
    "omp.atomic.no-alias": [
        _c(M52, "4.3.1.3", 84, "30-31",
           "None of v, expr, and expr-list (as applicable) may access the same storage location as x.")],
    "omp.atomic.exclusive-across-teams": [
        _c(M52, "15.8.4", 311, "25-27",
           "atomic regions enforce exclusive access with respect to other atomic regions that access the same storage location x")],
    "omp.atomic.captured-update": [
        _c(M52, "15.8.4", 312, "1-4",
           "If the capture clause is present, the atomic update is an atomic captured update")],
    "omp.atomic.protect-all": [
        _c(M52, "15.8.4", 312, "38-39",
           "all accesses of the locations designated by x that could potentially occur in parallel must be protected with an atomic construct.")],
    "omp.atomic.no-constructs": [
        _c(M52, "15.8.4", 313, "33",
           "OpenMP constructs may not be encountered during execution of an atomic region.")],
    "omp.has-device-addr": [
        _c(M52, "5.4.9", 123, "3-6",
           "If the device address of a list item is not for the device on which the region that is associated with the construct on which the clause appears executes, accessing the list item inside the region results in unspecified behavior.")],
    "omp.collapse": [
        _c(M52, "4.4.3", 93, "23-25",
           "The collapse clause associates one or more loops with the directive on which it appears")],
}


def rows_for(tags) -> list[dict]:
    seen, out = set(), []
    for t in tags:
        for r in CITES.get(t, ()):
            k = (r["version"], r["page"], r["lines"])
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out


def cite_text(r: dict) -> str:
    return (f"{r['version']} §{r['section']} p.{r['page']} l.{r['lines']}: "
            f"\"{r['quote']}\"")
