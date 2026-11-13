"""nested-data: the spec rows the generated programs stress.

Each tag names one rule; its rows are citations in the form
offload.engine.dataenv_rules.check_citation checks against results/spec_cache/
(version, section, printed page, margin lines, a verbatim piece of those
lines). Every generated program lists the tags of the rules it exercises
(``offload.engine.nested_gen.Program.rules``) and, from them, the rows
(``rows_for``); the site shows the rows.

Pages and lines are those of the printed OpenMP 5.2 / 6.0 and OpenACC 3.4
documents. The pointer-attachment rule is the one the whole campaign rests
on: 5.2 words it for the map-entering construct ("a corresponding pointer
exists ... upon entry"), 6.0 for the constructs' effective map clause set
("after all mappable storage blocks are mapped"), which fixes the order of
the list items on one construct.
"""
from __future__ import annotations


def _c(version, section, page, lines, quote):
    return {"version": version, "section": section, "page": page,
            "lines": lines, "quote": quote}


M52, M60, A34 = "OpenMP 5.2", "OpenMP 6.0", "OpenACC 3.4"

CITES: dict[str, list[dict]] = {
    # --- OpenMP: the map clause, pointer attachment ---------------------------
    "omp.map.struct-elements": [
        _c(M52, "5.8.3", 151, "13", "The list items that appear in a map clause may include array sections "
           "and structure elements.")],
    "omp.map.attach": [
        _c(M52, "5.8.3", 152, "5-7", "if any list item has a base pointer for which a corresponding pointer "
           "exists in the data environment upon entry to the region and either a new list item"),
        _c(M52, "5.8.3", 152, "14", "The corresponding pointer variable becomes an attached pointer for the "
           "corresponding list item."),
        _c(M60, "7.9.6", 284, "8-10", "for which a corresponding pointer exists in the device data environment "
           "after all mappable storage blocks are mapped")],
    "omp.map.fortran-pointer-target": [
        _c(M52, "5.8.3", 152, "1-3", "If a list item in a map clause is an associated pointer and the pointer "
           "is not the base pointer of another list item in a map clause on the same construct")],
    "omp.map.fortran-components": [
        _c(M52, "5.8.3", 151, "32", "If it has the POINTER attribute, the map clause treats its association "
           "status as if it is undefined"),
        _c(M52, "5.8.3", 151, "34-35", "If it has the ALLOCATABLE attribute and an allocated allocation status, "
           "and it is present in the device data environment when the construct is encountered"),
        _c(M60, "7.9.6", 282, "12", "If it has the POINTER attribute, it is attach-ineligible")],
    "omp.map.default-mapper": [
        _c(M52, "5.8.2", 150, "2-4", "A structure type T has a predefined default mapper that is defined as "
           "if by a declare mapper directive that specifies v in a map clause with the alloc map-type")],
    "omp.map.same-storage": [
        _c(M52, "5.8.3", 156, "6-7", "Two list items of the map clauses on the same construct must not share "
           "original storage unless they are the same list item or unless one is the containing structure "
           "of the other.")],
    "omp.map.storage-block": [
        _c(M52, "5.8.3", 152, "29-30", "All map clause list items that have the same containing structure or "
           "share storage result in a single mappable storage block")],
    "omp.map.struct-element-others": [
        _c(M52, "13.8", 286, "27-28", "If a list item in a map clause is a structure element, any other "
           "element of that structure that is referenced in the target construct must also appear")],
    "omp.map.partly-present": [
        _c(M52, "5.8.3", 156, "19-22", "If any part of the original storage of a list item with an explicit "
           "data-mapping attribute has corresponding storage in the device data environment")],
    "omp.map.always": [
        _c(M52, "5.8.3", 153, "15-17", "or if the always map-type-modifier is specified, and if the map-type "
           "is to or tofrom, the corresponding list item is updated"),
        _c(M52, "5.8.3", 154, "2-5", "or if the always map-type-modifier is specified, and if the map-type "
           "is from or tofrom, the original list item is updated")],
    "omp.map.present": [
        _c(M52, "5.8.3", 152, "25-27", "If a map clause with a present map-type-modifier appears on a "
           "construct and on entry to the region the corresponding list item is not present")],
    "omp.map.close": [
        _c(M52, "5.8.3", 155, "12", "The close map-type-modifier is a hint to the runtime to allocate "
           "memory close to the target device.")],
    "omp.map.refcount": [
        _c(M52, "5.8.3", 154, "10-11", "If the reference count of the corresponding storage block is zero, "
           "all storage to which that reference count applies is removed")],
    "omp.map.attached-unmodified": [
        _c(M52, "5.8.3", 157, "12-14", "A pointer that has a corresponding attached pointer must not be "
           "modified for the duration of the lifetime of the list item"),
        _c(M52, "13.8", 287, "7", "An attached pointer must not be modified in a target region.")],
    "omp.map.alloc-status": [
        _c(M52, "13.8", 287, "25-27", "If the allocation status of a mapped variable that has the ALLOCATABLE "
           "attribute is allocated on entry to a target region")],
    "omp.map.pointer-association": [
        _c(M52, "13.8", 287, "29-31", "If the association status of a list item with the POINTER attribute "
           "that appears in a map clause on the construct is associated upon entry")],
    # --- OpenMP: implicit mapping, pointer lookup ------------------------------
    "omp.implicit.pointer": [
        _c(M52, "5.8.1", 148, "29-31", "is treated as if it is the base pointer of a zero-length array "
           "section that had appeared as a list item in a map clause"),
        _c(M52, "5.1.1", 98, "2-4", "the base pointer is a scalar variable that does not appear in a map "
           "clause on the construct, the base pointer is firstprivate")],
    "omp.implicit.lookup": [
        _c(M52, "5.8.6", 160, "22-23", "If the value of a given pointer is in the mapped address range of a "
           "currently mapped list item"),
        _c(M52, "5.8.6", 160, "29-31", "the initial value that is assigned to the pointer is a device address "
           "such that the corresponding list item in the device data environment can be accessed")],
    "omp.implicit.nonscalar": [
        _c(M52, "5.8.1", 149, "4-5", "If a variable is not a scalar then it is treated as if it had "
           "appeared in a map clause with a map-type of tofrom.")],
    # --- OpenMP: motion clauses --------------------------------------------------
    "omp.update.attached": [
        _c(M52, "5.9", 166, "5-7", "if the corresponding list item is an attached pointer, the original "
           "list item will have the value it had on entry to the region")],
    "omp.update.pointer": [
        _c(M52, "5.9", 165, "29-31", "If a list item has the POINTER attribute and its association status "
           "is associated, the effect is as if the assignment is performed with respect to the pointer "
           "target.")],
    "omp.update.allocatable": [
        _c(M52, "5.9", 165, "28-29", "If a list item or a subobject of a list item has the ALLOCATABLE "
           "attribute, its assignment is performed only if its allocation status is allocated")],
    # --- OpenMP: declare mapper --------------------------------------------------
    "omp.mapper.decay": [
        _c(M52, "5.8.8", 163, "18-19", "The final map types that a mapper applies for a map clause that "
           "maps a list item of the given type are determined according to the rules of map-type decay")],
    "omp.mapper.nested": [
        _c(M52, "5.8.8", 164, "1-2", "All map clauses that are introduced by a mapper are further subject to "
           "mappers that are in scope")],
    "omp.mapper.cycle": [
        _c(M52, "5.8.8", 164, "9-10", "If a set of declare mapper directives results in a cyclic definition "
           "then the behavior is unspecified.")],
    "omp.mapper.array": [
        _c(M52, "5.8.3", 151, "26-27", "A list item that is an array or array section of a type for which a "
           "user-defined mapper exists is mapped as if the map type decays to alloc, release, or delete")],
    "omp.declare-target.procs": [
        _c(M52, "13.8", 285, "2-3", "that procedure is treated as if its name had appeared in an enter "
           "clause on a declare target directive")],
    # --- OpenACC -----------------------------------------------------------------
    "acc.composite.c": [
        _c(A34, "2.7.1", 49, "1708-1710", "If a composite member is a pointer type, the data addressed by "
           "that pointer are not implicitly copied.")],
    "acc.composite.fortran": [
        _c(A34, "2.7.1", 50, "1711-1713", "If any member has the allocatable or pointer attribute, the data "
           "accessed through that member are not copied.")],
    "acc.host-pointer-copied": [
        _c(A34, "2.6.4", 43, "1445-1446", "the pointer value copied to device memory will be the host "
           "pointer value.")],
    "acc.attach.action": [
        _c(A34, "2.7.2", 51, "1779", "An attach pointer action for a var occurs only when var is a pointer "
           "reference."),
        _c(A34, "2.7.2", 52, "1785-1786", "The implementation schedules pointer updates after any data "
           "transfers due to transfer in actions")],
    "acc.attach.null": [
        _c(A34, "2.7.2", 51, "1782-1783", "If the pointer is a null pointer, the pointer in device-accessible "
           "memory is updated to have the same value.")],
    "acc.copyin.attach": [
        _c(A34, "2.7.8", 55, "1902-1903", "If var is a pointer reference, an attach pointer action is "
           "performed followed by an increment counter action")],
    "acc.attach.clause": [
        _c(A34, "2.7.13", 59, "2039-2040", "Each var argument to an attach clause must be a C or C++ pointer "
           "or a Fortran variable or array with the pointer or allocatable attribute."),
        _c(A34, "2.7.13", 59, "2043-2044", "At entry to a region or at an enter data directive, an attach "
           "pointer action is performed")],
    "acc.detach": [
        _c(A34, "2.7.14", 59, "2058", "If the attachment counter is now zero, a detach pointer action is "
           "performed."),
        _c(A34, "2.7.2", 52, "1798-1799", "The implementation schedules pointer updates before any data "
           "transfers due to transfer out actions")],
    "acc.restore-host-pointer": [
        _c(A34, "2.6.4", 43, "1451-1453", "When the device pointer target is deallocated, the pointer in "
           "device memory is restored to the host value")],
    "acc.composite-update-attached": [
        _c(A34, "2.6.8", 48, "1637-1639", "The behavior of the program is undefined if any of the pointer "
           "members are attached when an update of a composite variable is performed.")],
    "acc.pointer-array": [
        _c(A34, "2.7.1", 49, "1686-1688", "the implementation will allocate pointers in device memory "
           "corresponding to the pointers in local memory and will fill in those pointers as appropriate"),
        _c(A34, "2.7.1", 49, "1700-1701", "modifying pointers in pointer arrays during the data lifetime, "
           "either on the host or on the device, may result in undefined behavior.")],
    "acc.fortran-array-pointer": [
        _c(A34, "2.7.1", 49, "1704-1705", "In Fortran, array pointers may appear, but pointer association "
           "is not preserved in device memory.")],
    "acc.pointer-assign-both": [
        _c(A34, "2.6.8", 48, "1634", "Unspecified behavior may result if both ways are used for the same "
           "pointer.")],
}


def rows_for(tags) -> list[dict]:
    """The citation rows of the tags (a tag's rows in the table's order,
    each row once)."""
    out, seen = [], set()
    for t in tags:
        for r in CITES[t]:
            k = (r["version"], r["section"], r["page"], r["lines"])
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out


def cite_text(r: dict) -> str:
    """``OpenMP 5.2 §5.8.3 p.152 l.5-7`` (the form offload.engine.citations
    reads)."""
    return f"{r['version']} §{r['section']} p.{r['page']} l.{r['lines']}"
