#!/usr/bin/env python3
"""The nested-data findings (data/findings/nested): which campaign programs each one stands for (a
predicate over the recorded cells, then only the cells the gate confirmed), the judgement items
(title, rule, legality, site text, README sentence), and the rebuild that writes
the finding files with tools/new_finding.py from the recorded rows.

    python3 -I tools/campaigns/nested_findings.py --list                  # the programs of each finding
    python3 -I tools/campaigns/nested_findings.py rebuild [KEY...]        # (re)write the findings

Run it on a compute node or a wingtip lane from a tree that holds results/ (never a login node).
A finding's facts (toolchains, modes, signature counts, gate counts, controls, other families)
come from the rows; nothing here states one.  `rebuild` first expects the nested entries to be
absent from data/findings/index.yaml and the table in data/findings/LOG.md
(tools/new_finding.py refuses to overwrite a finding).  The reduction and control sources are
results/nested/red/*.c|f90 and their rows results/nested/red/*.jsonl.
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import os
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

RED = "results/nested/red"
CAMPAIGNS = ("main", "big")
SECTION = "Nested pointer-linked data"


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def fam(r) -> str:
    """The compiler family of a row (the catalog's, offload.engine.confirm.machines)."""
    from offload.engine.confirm.machines import family_of
    return family_of(r["toolchain"])


def _cls(r) -> str:
    """The outcome class of a row (tools/campaigns/nested.py)."""
    return _load("nested_tool", "tools/campaigns/nested.py")._cls(r)


def reason(r) -> str:
    return (r.get("reason") or "") + (r.get("stderr") or "")


# The findings.  pred(row, program): the campaign cells that fail with the finding's signature (the
# programs it stands for are those cells that the gate confirmed); fam: the compiler family the
# finding is about (its reduction picks the signature); exclude: programs left out (a gate
# placement the claim checker cannot accept); note: a run condition the rows alone do not state,
# written as a `run condition` bullet with its evidence; devices: the toolchains the site matrix runs
# with every device of the node visible (the site block's `devices: all TC...`); counted_arch: GPU arch -> why
# the family's toolchain on it, whose failure is reported differently, is this finding's (tools/new_finding.py
# `same`); primary_arch: the arch of the headline toolchains when the family's platforms would tie on failing
# rows. Toolchains are named by arch and resolved through the catalog (`_of_arch`): no toolchain id in this file.
SPEC = {
    'update': dict(
        file='afar-cce-c-update-struct-and-member-rejected.c',
        lang='c',
        title="AFAR and CCE (clang front end) reject target update with a structure and one of its pointer members' arrays in one clause",
        repro='u1-update-struct-and-member-heap.c',
        also='u2-update-struct-and-member-var.c',
        controls=['u3-ctl-update-member-only.c', 'u4-ctl-two-updates.c', 'u5-ctl-same-list-in-map.c'],
        pred=lambda r, p: fam(r) in ('afar', 'cce') and r['outcome'] == 'rejected' and re.search('same pointer dereferenced|variable can appear only once', reason(r)),
        rule='the list items of a data-motion clause are locators; "The list items that appear in a map clause may include array sections and structure elements" (5.2 §5.8.3 p.151 l.13) and a to or from clause on target update names list items the same way (§5.9 p.165 l.7-14); the restrictions of data-motion clauses are only "Each list item clause must have a mappable type." (5.2 §5.9 p.166 l.13-14); the target update construct has no restriction on two list items with one base variable (§13.9 p.289)',
        legality="the rules (offload.engine.rules) accept it; GCC compiles and runs it (GCC is no legality witness); the AFAR/CCE C front ends reject it with a diagnostic, so the only other front end is NVHPC nvc, which accepted the campaign's update programs of this form where it ran at all (results/nested/main/witness*.jsonl)",
    ),
    'afarroot': dict(
        file='afar-flang-pointer-root-allocatable-component-enter-data-fault.f90',
        lang='f90',
        title='AFAR flang, copy mode: a derived-type object reached through a pointer (the root, or a pointer component) with an allocatable component, mapped by enter data, makes the kernel fault',
        repro='m1-pointer-root-allocatable-component.f90',
        also='q1-pointer-component-with-allocatable.f90',
        controls=['m2-ctl-variable-root.f90', 'm3-ctl-fixed-array-component.f90', 'm5-ctl-no-enter-data.f90', 'q2-ctl-fixed-array.f90', 'q3-ctl-allocatable-component-of-the-variable.f90'],
        pred=lambda r, p: fam(r) == 'afar' and p.lang == 'f90' and (r['mode'] == 'copy') and (p.legality == 'defined') and (_cls(r) not in ('correct_on_device', 'unobservable', 'harness_error')) and ('alloc' in p.axes['datas'] or 'alloc' in p.axes['links'] or 'aarr' in p.axes['links']) and ('MEMORY_FAULT' in reason(r)),
        rule='the structure is mapped by the target enter data directive and "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom" (5.2 §5.8.1 p.149 l.4-5), so a reference in the later target region finds it present; an allocatable component of a mapped derived type is mapped with it by the predefined default mapper (5.2 §5.8.2 p.150 l.2-4)',
        legality="the rules (offload.engine.rules) accept it, AFAR's flang front end accepts it and CCE compiles and runs it (the front ends of two other families)",
    ),
    'cceice': dict(
        file='cce-c-struct-and-nested-pointee-sections-ice.c',
        lang='c',
        title='CCE craycc crashes in CodeGen: a target construct maps a structure and the structure and array reached through an embedded structure and a pointer',
        repro='j5-struct-and-nested-pointees.c',
        also=None,
        controls=['j1-embedded-struct-pointer-to-struct.c', 'j6-ctl-struct-and-one-pointee-level.c', 'j7-ctl-struct-and-embedded-pointee.c', 'j2-ctl-pointer-instead-of-embedded.c'],
        pred=lambda r, p: fam(r) == 'cce' and p.lang == 'c' and (r['outcome'] in ('ice', 'rejected')) and ('PLEASE submit a bug report' in reason(r)),
        rule='"A structure and an element of it may both be list items" in the sense of 5.2 §5.8.3 p.156 l.6-7 ("unless one is the containing structure of the other"), and a section reached through pointer members is a list item of a map clause (§5.8.3 p.151 l.13); the construct maps r, then r.nx.nx[0:1] and r.nx.nx->a[0:8] through the embedded structure r.nx and its pointer member',
        legality="the rules (offload.engine.rules) accept it; AFAR's clang compiles and runs it (a front end of another family)",
    ),
    'ccenest': dict(
        file='cce-fortran-nested-allocatable-component-copy-fault.f90',
        lang='f90',
        title='CCE, copy mode: a derived type with a derived-type component that holds an allocatable array, mapped by enter data, makes the kernel fail',
        repro='n7-two-level-allocatable.f90',
        also=None,
        controls=['n8-ctl-fixed-array-in-component.f90', 'n9-ctl-allocatable-in-the-variable.f90'],
        rule='a structure type has a predefined default mapper that maps its elements (OpenMP 5.2 §5.8.2 p.150 l.2-4: "A structure type T has a predefined default mapper that is defined as if by a declare mapper directive that specifies v in a map clause with the alloc map-type"), and the map clauses a mapper introduces are subject to the mappers in scope (§5.8.8 p.164 l.1: "All map clauses that are introduced by a mapper are further subject to mappers that are in scope"), so the default mapper of the component\'s derived type maps its allocatable array too; the program references nothing else',
        legality='the rules (offload.engine.rules) accept it; AFAR compiles and runs it correctly (a front end of another family)',
    ),
    'accshared': dict(
        file='gcc-acc-c-parent-and-shared-pointee-one-directive.c',
        lang='c',
        title='GCC OpenACC: copyin of a new parent and of its pointer member\'s target, which is already present, in one enter data directive stops at run time: "enclosing struct not mapped for attach"',
        repro='e1-second-parent-with-its-pointee-one-directive.c',
        also=None,
        controls=['e2-ctl-two-directives.c', 'e3-ctl-attach-clause.c'],
        pred=lambda r, p: fam(r) == 'gcc' and p.axes['lang'] == 'c' and (p.axes['model'] == 'acc') and ('enclosing struct not mapped for attach' in reason(r)),
        rule='OpenACC 3.4 §2.7.8 p.55 l.1902-1903: "If var is a pointer reference, an attach pointer action is performed followed by an increment counter action"; attach actions are scheduled after the transfers of the same directive (§2.7.2 p.52 l.1785-1786), and the target of the pointer is present (it was mapped by the first parent)',
        legality='the rules (offload.engine.rules) accept it; both NVHPC releases compile and run the reduction correctly (a compiler of another family; the registry has no OpenACC C clause checker, so this is acceptance and execution, not a clause check)',
    ),
    'accpp': dict(
        file='gcc-acc-c-exit-data-of-a-pointer-array-element-target-hangs.c',
        lang='c',
        title='GCC OpenACC: exit data of the target of an element of a pointer array stops at run time: "goacc_exit_data_internal UNHANDLED kind 0x50" (the program hangs)',
        repro='f4-one-element.c',
        also=None,
        controls=['f3-pointer-array-only.c', 'f5-ctl-copyout-exit.c', 'f6-ctl-pointer-to-struct-array.c'],
        pred=lambda r, p: fam(r) == 'gcc' and p.axes['lang'] == 'c' and (p.axes['model'] == 'acc') and ('UNHANDLED kind' in reason(r)),
        rule='OpenACC 3.4 §2.7.1 p.49 l.1686-1688 describes how the pointers of dynamically allocated dimensions are filled in; the text has no sentence that names a subarray of the target of an element of a pointer array (r.nx[0][0:1]) as a var form, so the legality of the program rests on the rules\' reading of var forms and on NVHPC accepting and running it. Exit data with delete or copyout of a var that is present decrements its counters and, for a pointer reference, its attachment counter (3.4 §2.7.12 p.58 l.2023-2024)',
        legality='the rules (offload.engine.rules) accept it; both NVHPC releases compile and run the reduction correctly (a compiler of another family; the registry has no OpenACC C clause checker, so this is acceptance and execution, not a clause check)',
    ),
    'nvorder': dict(
        imsg='CUDA_ERROR_ILLEGAL_ADDRESS (pointee listed before its parent)',
        file='nvhpc-c-pointee-before-parent-in-one-map-list-copy-fault.c',
        lang='c',
        title='NVHPC, separate memory: a target construct that lists the pointee of a pointer member before the structure that holds the pointer fails with CUDA_ERROR_ILLEGAL_ADDRESS (the other order is correct)',
        repro='v1-pointer-member-then-parent-one-directive.c',
        also=None,
        controls=['v2-ctl-parent-first.c', 'v4-ctl-embedded-member.c'],
        rule='attachment is decided on the storage of the whole construct: OpenMP 6.0 §7.9.6 p.284 l.8-10: "for which a corresponding pointer exists in the device data environment after all mappable storage blocks are mapped" (the OpenMP 5.2 text at §5.8.3 p.152 l.5-7 is worded for the state on entry and is weaker; the finding rests on the 6.0 wording), so the order of the clauses of one construct does not change the result',
        legality='the rules (offload.engine.rules) accept it; AFAR and CCE compile and run it correctly (front ends of two other families)',
    ),
    'ccetyped': dict(
        imsg='CRAY_ACC_ERROR - unsupported flags for typed transfer',
        file='cce-fortran-pointer-to-type-with-allocatable-scalar-component-typed-transfer.f90',
        lang='f90',
        title='CCE, both modes: a variable with a pointer component to a derived type that has an allocatable scalar component of derived type fails at enter data with "unsupported flags for typed transfer"',
        repro='ta1-pointer-to-type-with-allocatable-scalar-component.f90',
        also=None,
        controls=['ta2-ctl-no-allocatable-component.f90', 'ta3-ctl-allocatable-scalar-in-the-variable.f90', 'ta4-ctl-pointer-component-only.f90'],
        pred=lambda r, p: fam(r) == 'cce' and p.lang == 'f90' and (p.axes['model'] == 'omp') and ('unsupported flags for typed transfer' in reason(r)),
        rule='a structure type has a predefined default mapper that maps its elements (OpenMP 5.2 §5.8.2 p.150 l.2-4: "A structure type T has a predefined default mapper that is defined as if by a declare mapper directive that specifies v in a map clause with the alloc map-type"); the variable r is entered with map(alloc: r) and left with map(from: r), its pointer component is not associated, and the target region touches only r%a and r%s',
        legality="the rules (offload.engine.rules) accept it; AFAR's flang front end and NVHPC accept it and run it correctly (front ends of two other families)",
    ),
    'gccmapptr': dict(
        fam='gcc',
        file='gcc-c-declare-mapper-pointer-member-section-gpu-fault.c',
        lang='c',
        title='GCC: a declare mapper for a structure with a pointer member that maps a section of the pointee makes the kernel fault on the GPU',
        repro='gp1-mapper-with-pointer-section.c',
        also='gp3-ctl-mapper-lists-members.c',
        controls=['gp2-ctl-no-mapper-explicit-maps.c'],
        pred=lambda r, p: fam(r) == 'gcc' and p.axes['lang'] == 'c' and p.axes['strategy'] in ('mapper', 'mapper_enter') and ('Memory access fault' in reason(r) or 'illegal memory access' in reason(r)),
        rule='OpenMP 5.2 §5.8.8 p.164 l.1-2: "All map clauses that are introduced by a mapper are further subject to mappers that are in scope, except a map clause with list item var maps var without invoking a mapper": the mapper maps the structure and a section of its pointer member, and a map(tofrom: r) applies it; the expected result relies on the mapper attaching that section to the device copy of r (inside the region r.a must refer to the device copy of r.a[0:NM])',
        legality='the rules (offload.engine.rules) accept it; AFAR and CCE compile and run it correctly (front ends of two other families); NVHPC does not accept the directive in C',
        note='on gfx90a the GPU fault shows with all eight MI250X GCDs of the node visible to the program (ROCR_VISIBLE_DEVICES unset: the nested campaign\'s and the gate\'s run environment): 20 of 20 repeat runs on tioga39 and tioga38 (2026-11-03), and the campaign program nd-c-omp-mapper-chain-d2-647b801f 10 of 10. With a single GCD visible (the site matrix pinned one GPU per run) the same binary completes with the correct sum in 40 of 40 runs, environments a-d on two nodes, on every GCD 0-7, and so does the campaign program; two GCDs visible fault 15 of 15, four pass 10 of 10. The control passes either way (10 of 10 with all eight visible). The visible set changes the host address layout after HSA initialization and nothing else, so in both outcomes the device dereferences the host address of r.a, which the mapper did not attach: the fault and the silently right sum are how that one missing mapping surfaces, not two defects. The A100 build fails 50 of 50 runs whatever is visible. The site matrix therefore runs this case with every device visible on the gfx90a toolchain (the site block\'s devices line). Logs and scripts: data/reports/nested-visibility/',
        devices_arch=['gfx90a'],
        primary_arch=['gfx90a'],
        counted_arch={'sm_80': 'on the A100 the CUDA runtime reports the same dereference of the unattached pointer as an illegal memory access (libgomp: cuCtxSynchronize error, exit status 1) where the HSA runtime on the MI250X aborts with a GPU memory access fault; one defect, reported differently by the two runtimes (50 of 50 repeat runs fail on the A100, data/reports/nested-visibility/wt_repeat.log)'},
    ),
    'gccalways': dict(
        fam='gcc',
        file='gcc-c-always-on-pointer-member-section-ice.c',
        lang='c',
        title='GCC: map(always, to:) of a section of a pointer member of an embedded structure crashes the compiler (error: Segmentation fault)',
        repro='gt4-ctl-always-on-section-only.c',
        also='gt1-always-on-structure-and-member-section.c',
        controls=['gt2-ctl-no-always.c', 'gt3-ctl-always-on-structure-only.c'],
        pred=lambda r, p: fam(r) == 'gcc' and p.axes['lang'] == 'c' and ('Segmentation fault' in reason(r)),
        rule='the always map-type-modifier may be given on any map clause list item, including a section of a pointer member reached through an embedded structure (OpenMP 5.2 §5.8.3 p.153 l.15-17)',
        legality='the rules (offload.engine.rules) accept it; AFAR, CCE and NVHPC compile and run it correctly (front ends of three other families)',
    ),
    'nvexit': dict(
        exclude=['nd-c-omp-enter-alias-d2-65d9ca10'],
        file='nvhpc-c-update-from-structure-overwrites-attached-pointer-segv.c',
        lang='c',
        title='NVHPC, separate memory: target update from() or exit data map(from:) of a structure whose pointer member is attached copies the device pointer back, and the next host access to the pointee crashes (SIGSEGV)',
        repro='nu2-ctl-update-in-two-directives.c',
        also='ns2-ctl-entered-once.c',
        controls=['nu3-ctl-update-pointee-only.c', 'ns8-ctl-enter-together-exit-split.c', 'ns4-ctl-two-directives-struct-then-pointee.c'],
        pred=lambda r, p: fam(r) == 'nvhpc' and p.axes['lang'] == 'c' and (p.axes['model'] == 'omp') and (r['mode'] == 'copy') and ('SIGSEGV' in reason(r)),
        rule='OpenMP 5.2 §5.9 p.166 l.5-7: "if the corresponding list item is an attached pointer, the original list item will have the value it had on entry to the region": a target update from() of a structure must not overwrite its pointer member while the member is attached (the same holds when exit data map(from:) copies the structure back before the pointee is released)',
        legality='the rules (offload.engine.rules) accept it; AFAR and CCE compile and run it correctly (front ends of two other families)',
    ),
    'cceupd': dict(
        imsg='CRAY_ACC_ERROR - host object does not appear to have an associated accelerator object',
        fam='cce',
        file='cce-fortran-update-to-pointer-root-allocatable-scalar-component-no-accelerator-object.f90',
        lang='f90',
        title='CCE: target update to() of a pointer to a derived type with an allocatable scalar component, entered with map(alloc:), fails: "host object does not appear to have an associated accelerator object"',
        repro='ua1-update-to-pointer-root-allocatable-scalar-component.f90',
        also=None,
        controls=['ua2-ctl-variable-root.f90', 'ua4-ctl-to-in-place-of-alloc-and-update.f90'],
        pred=lambda r, p: fam(r) == 'cce' and p.lang == 'f90' and (p.axes['model'] == 'omp') and ('does not appear to have an associated accelerator object' in reason(r)),
        rule='a list item with an allocatable subobject is updated only if the subobject is allocated (OpenMP 5.2 §5.9 p.165 l.28-29: "If a list item or a subobject of a list item has the ALLOCATABLE attribute, its assignment is performed only if its allocation status is allocated"); the structure was entered with map(alloc: r), whose default mapper maps the allocated component (§5.8.2 p.150 l.2-4), so the update has a device copy to write',
        legality='the rules (offload.engine.rules) accept it; AFAR compiles it (a front end of another family; AFAR fails the pointer-root shape at run time for its own reason, which its map(to:) control shares)',
    ),
    'callresult': dict(
        file='afar-cce-c-call-result-member-in-target-rejected.c',
        lang='c',
        title='AFAR and CCE (clang front end) reject a member access through a call result inside a target region: "expected addressable lvalue in \'map\' clause"',
        repro='p1-call-result-member.c',
        also=None,
        controls=['p2-ctl-pointer-variable.c', 'p3-ctl-direct-member.c'],
        pred=lambda r, p: fam(r) in ('afar', 'cce') and r['outcome'] == 'rejected' and ('expected addressable lvalue' in reason(r)),
        rule='only variables referenced in a target construct get an implicit data-mapping attribute: "the first matching rule from the following list determines the implicit data-mapping (or data-sharing) attribute for variables referenced in a target construct" (5.2 §5.8.1 p.148 l.3-5); the member `child(r)->a` is a structure element reached through a function result, not a variable, and r->nx->a[0:4] is mapped explicitly',
        legality='the rules (offload.engine.rules) accept it; GCC compiles and runs it; the clang front ends of AFAR and CCE are the two compilers that reject it (they share a lineage, so neither witnesses the other)',
    ),
    'ptrbounds': dict(
        drop_sigcount=True,
        expected='compiles and prints `tot= 4028`, `s= 900` with `check=pass` (the model of the program: the sum of the written values)',
        file='gcc-fortran-pointer-component-alloc-bounds-lost.f90',
        lang='f90',
        title='GCC: a pointer component mapped alloc and written on the device comes back with the wrong values (bounds of the attached descriptor not set)',
        repro='g2-ptr-alloc-member-then-parent.f90',
        also=None,
        controls=['g2-ctl-entered-to.f90', 'g2-ctl-allocatable.f90'],
        rule='on entry the corresponding pointer "is associated with a pointer target that has the same rank and bounds as the pointer target of the original pointer, such that the corresponding list item can be accessed through the pointer in a target region" (5.2 §5.8.3 p.152 l.11-13); the structure is entered with map(alloc:), so its descriptor is not initialized by a transfer and has to be set by the attach',
        legality="the rules (offload.engine.rules) accept it, AFAR's flang front end accepts it",
    ),
    'iceptr': dict(
        fam='gcc',
        file='gcc-fortran-root-and-element-pointer-components-ice.f90',
        lang='f90',
        title='GCC ICE in gimplify_adjust_omp_clauses: a pointer component of the root and the pointer components of the elements of an allocatable component array in one map list',
        repro='g5-root-pointer-and-element-pointers.f90',
        also=None,
        controls=['g5-ctl-element-pointers-only.f90', 'g5-ctl-root-pointer-only.f90'],
        pred=lambda r, p: fam(r) == 'gcc' and r['outcome'] in ('ice', 'rejected') and ('in gimplify_adjust_omp_clauses' in (r.get('reason') or '')),
        rule='pointer components are list items when they appear in a map clause ("The list items that appear in a map clause may include array sections and structure elements", 5.2 §5.8.3 p.151 l.13); the construct names a pointer component of the root and the pointer components of the elements of an allocatable array component, none of them the base pointer of another item (5.2 §5.8.3 p.152 l.1-3)',
        legality="the rules (offload.engine.rules) accept it and AFAR's flang front end accepts it",
    ),
    'fromstruct': dict(
        fam='gcc',
        file='gcc-c-from-struct-and-pointee-section-rejected.c',
        lang='c',
        title='GCC rejects map(from: r) together with a section a pointer-array member points to: "map-type other than to, from, tofrom or alloc"',
        repro='g3-ptrs-from-struct.c',
        also=None,
        controls=['g3-ctl-from-struct-no-element.c', 'g3-ptrs-two-elements-to.c', 'g3-ptrs-two-elements-tofrom.c'],
        pred=lambda r, p: fam(r) == 'gcc' and r['outcome'] == 'rejected' and ('map-type other than' in reason(r)) and (p.lang == 'c'),
        rule='"A map-type in a map clause must be to, from, tofrom or alloc." (5.2 §13.8 p.286 l.33) and map(from:) is one of them; a structure and an element of it may both be list items: "Two list items of the map clauses on the same construct must not share original storage unless they are the same list item or unless one is the containing structure of the other." (5.2 §5.8.3 p.156 l.6-7); the section r.nx[0][0:1] is storage the pointer member points to, not part of r',
        legality="the rules accept it; AFAR's clang front end accepts it",
    ),
    'accdata': dict(
        file='gcc-acc-c-struct-and-member-array-one-directive.c',
        lang='c',
        title='GCC OpenACC: copyin of a structure and of the array its pointer member points to in one data directive stops at run time: "outer struct not mapped for attach"',
        repro='c1-acc-data-struct-and-array.c',
        also='c4-acc-enter-data-struct-and-array.c',
        controls=['c3-ctl-nested-data.c', 'c5-acc-serial-struct-and-array.c'],
        pred=lambda r, p: fam(r) == 'gcc' and p.axes['lang'] == 'c' and (p.axes['model'] == 'acc') and ('outer struct not mapped for attach' in reason(r)),
        rule='OpenACC 3.4 §2.7.8 p.55 l.1902-1903: "If var is a pointer reference, an attach pointer action is performed followed by an increment counter action"; the attach actions of a directive are scheduled after its transfers: "The implementation schedules pointer updates after any data transfers due to transfer in actions that are performed for the same directive." (§2.7.2 p.52 l.1785-1786), so the structure and the array its member points to may be mapped by one directive',
        legality='the rules (offload.engine.rules) accept it; both NVHPC releases compile and run the reduction correctly (a compiler of another family; the registry has no OpenACC C clause checker, so this is acceptance and execution, not a clause check)',
    ),
}


TEXT = {
    'accdata': dict(what='copyin of a structure and of the array its pointer member points to in one data directive stops at run time ("outer struct not mapped for attach")', site=('GCC OpenACC: structure and member array in one data directive stops at run time', 'GCC stops with "outer struct not mapped for attach" at a data directive naming a structure and its pointee array.')),
    'accpp': dict(what='exit data of the target of an element of a pointer array: "goacc_exit_data_internal UNHANDLED kind 0x50" and the program does not end', site=('GCC OpenACC: exit data of a pointer-array element target hangs', 'GCC prints "UNHANDLED kind 0x50" and hangs after exit data of an element target of a pointer array.')),
    'accshared': dict(what='copyin of a new parent and of its pointer member\'s target, already present, in one enter data directive stops at run time ("enclosing struct not mapped for attach")', site=('GCC OpenACC: second parent of a present pointee stops at run time', 'GCC stops with "enclosing struct not mapped for attach" at an enter data naming a second parent of a present pointee.')),
    'afarroot': dict(what='in copy mode (HSA_XNACK=0) a Fortran pointer to a derived type with an allocatable component, mapped by target enter data and used in a target region without a map clause, makes the kernel fault', site=('AFAR: pointer-root derived type with allocatable component faults in copy mode', 'AFAR faults in copy mode on a Fortran pointer to a derived type with an allocatable component entered by enter data.')),
    'callresult': dict(what='a member access through a function call result inside a target region is rejected ("expected addressable lvalue in \'map\' clause")', site=('AFAR and CCE: member of a function result in a target region rejected', 'AFAR and CCE reject a member access through a function call result inside a target region.')),
    'cceice': dict(what='a target construct that maps a structure and, through an embedded structure and a pointer member, a second structure and its array: the compiler crashes', site=('CCE: compiler crash on nested pointee sections in one target construct', 'The CCE front end crashes on a target construct mapping nested structures through pointer members.')),
    'ccenest': dict(what='in copy mode (HSA_XNACK=0) a derived-type variable whose component is a derived type with an allocatable array, mapped by target enter data, makes the kernel fail (hipErrorIllegalAddress; abort on CCE 19/20)', site=('CCE: nested allocatable component faults in copy mode', 'CCE fails in copy mode on a derived type whose component is a derived type holding an allocatable array.')),
    'ccetyped': dict(what='a variable with a pointer component to a derived type that has an allocatable scalar component of derived type fails at target enter data with "unsupported flags for typed transfer"', site=('CCE: "unsupported flags for typed transfer" for a nested allocatable scalar component', 'CCE aborts enter data of a variable whose pointer component points to a type with an allocatable scalar component.')),
    'cceupd': dict(what='target update to() of a pointer to a derived type with an allocatable scalar component, entered with map(alloc:), fails with "host object does not appear to have an associated accelerator object"', site=('CCE: update to of a pointer root with an allocatable scalar component fails', 'CCE stops at target update to() of a pointer root with an allocatable scalar component.')),
    'fromstruct': dict(what='map(from: r) with a section a pointer-array member points to is rejected with "map-type other than to, from, tofrom or alloc"', site=('GCC: map(from:) of a structure with a pointee section rejected', 'GCC rejects map(from: r) combined with a section of a pointer-array member.')),
    'gccalways': dict(what='map(always, to:) of a section of a pointer member of an embedded structure crashes the compiler: error: Segmentation fault', site=('GCC: compiler crash on map(always) of a pointer-member section', 'GCC crashes on map(always, to:) of a section of a pointer member of an embedded structure.')),
    'gccmapptr': dict(what='a declare mapper for a structure with a pointer member, mapping a section of the pointee, makes the kernel fault on the GPU', site=('GCC: declare mapper with a pointer-member section faults on the GPU', 'GCC kernels fault when a declare mapper maps a section of a pointer member.')),
    'iceptr': dict(what='a pointer component of the root with the pointer components of the elements of an allocatable component array in one map list: ICE in gimplify_adjust_omp_clauses', site=('GCC Fortran: compiler crash on root and element pointer components in one map list', 'GCC crashes in gimplify_adjust_omp_clauses on a root pointer component and element pointer components in one map list.')),
    'nvexit': dict(what='in separate memory target update from() or exit data map(from:) of a structure whose pointer member is attached copies the device pointer back and the next host access crashes with SIGSEGV', site=('NVHPC: update from of a structure overwrites its attached pointer member', 'NVHPC update from() of a structure copies the device pointer back and the next host access crashes.')),
    'nvorder': dict(what='in separate memory a target construct that lists the pointee of a pointer member before the structure that holds the pointer fails with CUDA_ERROR_ILLEGAL_ADDRESS', site=('NVHPC: pointee listed before its parent in one map list faults in separate memory', 'In separate memory NVHPC faults when a map list names a pointee before the structure holding the pointer.')),
    'ptrbounds': dict(what='a Fortran pointer component entered with map(alloc:) and written on the device comes back with wrong values', site=('GCC Fortran: pointer component entered with alloc comes back with wrong values', 'GCC returns wrong values for a Fortran pointer component entered with map(alloc:).')),
    'update': dict(what='target update to/from with a structure and the array one of its pointer members points to in one clause is rejected ("same pointer dereferenced in multiple different ways", "variable can appear only once")', site=('target update with a structure and a member array in one clause rejected', 'AFAR and CCE reject a target update clause naming a structure and the array its pointer member points to.')),
}


# --- the campaign cells ----------------------------------------------------------------------------

def campaign_cells():
    """(rows, programs, gate verdicts) of both draws, merged by cell."""
    N = _load("nested_tool", "tools/campaigns/nested.py")
    N._register()
    ps, ver, rows = {}, {}, {}
    for camp in CAMPAIGNS:
        ps.update({p.id: p for p in N.programs(camp)})
        ver.update(N.verdicts(camp))
        rows.update({(r["program_id"], r["toolchain"], r["xnack"]): r for r in N.rows(camp)})
    return N, ps, ver, rows


def programs_of(key: str, cells=None, toolchains=None) -> list[str]:
    """The programs of finding `key`: those with a cell that satisfies its predicate and that the
    campaign gate confirmed (a cell the gate calls nondeterministic or environment-dependent is
    not an instance); with `toolchains`, only the cells of those (the finding's own)."""
    s = SPEC[key]
    pred = s.get("same") or s.get("pred")
    if not pred:
        return []
    N, ps, ver, rows = cells or campaign_cells()
    out = set()
    for (pid, tc, x), r in rows.items():
        p = ps[pid]
        if p.legality != "defined" or (toolchains and tc not in toolchains):
            continue
        if pred(r, p) and ver.get(f"nested|{pid}|{tc}|{x}", {}).get("verdict") == "confirmed":
            out.add(pid)
    return sorted(out - set(s.get("exclude", ())))


def _of_arch(s: dict, arches) -> list[str]:
    """The toolchains of the finding's family on these GPU architectures (catalog order)."""
    from offload.engine.site import matrix as M
    from offload.engine.confirm.machines import family_of
    from offload.engine.toolchains import registry
    R = registry()
    return [t for t in M.TOOLCHAINS if arches and family_of(t) == s.get("fam") and R.toolchains[t].arch in arches]


def rebuild(keys=()) -> list[str]:
    NF = _load("new_finding", "tools/new_finding.py")
    from offload.engine.site import matrix as M
    from offload.engine.confirm.machines import family_of
    cells = campaign_cells()
    rows = (sorted(glob.glob(f"{RED}/*.jsonl")) + sorted(glob.glob("results/nested/main/rows.part.*.jsonl"))
            + sorted(glob.glob("results/nested/big/rows.part.*.jsonl"))
            + sorted(glob.glob("results/findings-baseline/nested-*.jsonl")))
    gate = (sorted(glob.glob("results/nested/main/gate_reruns.part.*.jsonl"))
            + sorted(glob.glob("results/nested/big/gate_reruns.part.*.jsonl")))
    log = []
    for k in keys or list(SPEC):
        s, t = SPEC[k], TEXT[k]
        mark = "//" if s["lang"] == "c" else "!"
        progs = programs_of(k, cells)
        name = s["file"].rsplit(".", 1)[0]
        # the toolchains the finding is about: named (`primary`: the reduction's own platform, when the
        # family's other platform has as many failing rows and would tie), else every one of its family
        primary = _of_arch(s, s.get("primary_arch")) or [tc for tc in M.TOOLCHAINS if s.get("fam") and family_of(tc) == s["fam"]]
        counted = {t: why for a, why in (s.get("counted_arch") or {}).items() for t in _of_arch(s, [a])}
        devices = _of_arch(s, s.get("devices_arch"))
        # a vendor check case for the finding (data/vendor/checks) adds its committed rows, as the claim
        # checker reads them
        case = M.case_for(f"nested/{name}", M._cases())

        def gen(pr):
            return NF.generate(f"{RED}/{s['repro']}", "nested-data", rows, [f"{RED}/{c}" for c in s["controls"]], name,
                               NF.ROOT, "nested", pr, (), case, gate, primary, same=counted)
        try:
            d = gen(progs)
            # the programs are the cells of the finding's own toolchains (the index entry's)
            import yaml
            tcs = yaml.safe_load(d.index_entry)[0]["toolchains"]
            own = programs_of(k, cells, tcs)
            if progs and own != progs:
                progs = own
                d = gen(progs)
        except NF.NoRows as e:
            log.append(f"{k}: NO ROWS {e}")
            continue
        x = d.text
        tl = textwrap.wrap(s["title"], 100, break_long_words=False)
        x = x.replace(f"{mark} # Finding (nested-data): {NF.TODO_TITLE}",
                      f"{mark} # Finding (nested-data): {tl[0]}" + "".join(f"\n{mark} # {y}" for y in tl[1:]))

        def block(key, text):
            return "\n".join(f"{mark} {y}" for y in textwrap.wrap(f"- {key}: {text}", 118, subsequent_indent="  ",
                                                                  break_long_words=False))
        x = x.replace(f"{mark} - rule: {NF.TODO_RULE}", block("rule", s["rule"]))
        legal = block("legality", s["legality"])
        if s.get("note"):   # a run condition the rows alone do not state, with its evidence
            legal = block("run condition", s["note"]) + "\n" + legal
        x = x.replace(f"{mark} - legality: {NF.TODO_LEGAL}", legal)
        if s.get("drop_sigcount"):
            # the committed check rows of this finding's case hold no failing run of the reduction, so the
            # claim checker cannot recompute the count from them (committed mode); the rows name the count
            x = re.sub(r"; identical signature on \d+ of \d+ failing cells", "", x)
        if s.get("expected"):
            # the expected output when the rows of several compilers that "pass" print different values
            x = re.sub(rf"(?m)^{re.escape(mark)} - expected: {re.escape(NF.H.MARK)}.*$", lambda m: block("expected", s["expected"]), x)
        st, ss = t["site"]
        x = x.replace(f"{mark} title: {NF.TODO_SITE_TITLE}", f"{mark} title: {st}")
        x = x.replace(f"{mark} summary: {NF.TODO_SITE_SUMMARY}", f"{mark} summary: {ss}")
        if devices:   # the site matrix leaves every device visible on these toolchains
            x = x.replace(f"{mark} end site", f"{mark} devices: all {' '.join(devices)}\n{mark} end site")
        d.text = x
        if s.get("imsg"):
            d.index_entry = re.sub(r"(?m)^(\s*message: ).*$", lambda m: m.group(1) + '"' + s["imsg"] + '"', d.index_entry)
        d.readme_row = d.readme_row.replace(f"{NF.H.MARK} one sentence", t["what"])
        left = NF.H.todos(d.text)
        NF.write(d, NF.ROOT, SECTION)
        log.append(f"{k}: {len(progs)} programs, TODO left {len(left)}" + ("; notes: " + " | ".join(d.notes) if d.notes else ""))
    return log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", nargs="?", choices=("rebuild", "list"), default="list")
    ap.add_argument("keys", nargs="*")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    keys = a.keys or list(SPEC)
    if a.cmd == "rebuild" and not a.list:
        print("\n".join(rebuild(keys)))
        return 0
    cells = campaign_cells()
    for k in keys:
        print(f"{k}: {len(programs_of(k, cells))} programs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
