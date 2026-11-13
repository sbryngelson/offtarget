#!/usr/bin/env python3
"""The decisions on the reproduction gate's review queue
 (97 rerun rows) as data: catalog/gate_queue.yaml.

The groups below are the decisions (legality first, then determinism);
each entry of the queue is assigned to one group by its index in
data/evidence/gate_probe/jobs.queue() (the queue's order: campaign, gate verdict,
signature) and checked against its cell. The observations of each entry
(the gate's own reruns, the probe runs of results/t48/, the gate-runner
reruns at low and at the gate's load) are tallied into the entry.
    python3 -I data/evidence/gate_probe/build_queue.py      # writes the YAML
    python3 -I data/evidence/gate_probe/gate_queue.py       # renders the page
Needs results/ (git-ignored): run where the probe outputs are."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

import jobs as J  # noqa: E402
import observed as O  # noqa: E402

R = ROOT / "results" / "t48"
PROBES = [R / f for f in ("batch1.out.jsonl", "batch2b.out.jsonl", "batch2d.out.jsonl",
                          "batch2c.out.jsonl", "batch2k.out.jsonl")]
# batch 1 built the OpenACC widen programs (91-94) with the OpenMP flags
# (the probe did not take the program's model yet): not evidence for them
NOT_EVIDENCE = {(R / "batch1.out.jsonl", k) for k in (91, 92, 93, 94)}
GATE_RERUNS = {"low": [R / "g4.low.jsonl", R / "g5.low.jsonl",
                       R / "g6.low.jsonl"],
               "high": [R / "g4.high.jsonl", R / "g5.high.jsonl",
                        R / "g6.high.jsonl"]}
TIOGA = R / "tioga.out.jsonl"

VERDICTS = ("illegal", "unspecified", "environment_defect",
            "nondeterministic_defect", "ours", "undecided")

# counts_as: what the cell should count as once decided: "failure" (a
# compiler or runtime defect, the observed failure class) or "none"
GROUPS = {
    "nvhpc-postdiag-crash": {
        "verdict": "nondeterministic_defect",
        "title": "NVHPC front end segfaults after its own severe diagnostic, intermittently",
        "legality": (
            "Legal for its version. acc34-clause-gang-dim: the atomic update "
            "b(i) = b(i) + 2*a(i) + 1 is x = x operator expr, which 'must be "
            "mathematically equivalent to x binop (expr)' (OpenACC 3.4 §2.12 "
            "p.78 l.2854-2856; ruling 2026-10-25: the precedence and "
            "parentheses forms are sufficient, not necessary; AFAR flang's "
            "rejection is a dispute note, not a witness). omp52-c-w-ordered: "
            "an ordered region binds to the innermost worksharing-loop region "
            "and needs an ordered clause of parameter one there (5.2 §15.10.2 "
            "p.331 l.16-17), which an ordered clause without n is (§4.4.4 p.94 "
            "l.18-19). fuzz n1x0-nvhpc269:58: thread_limit on target is 5.2 "
            "(§13.3 p.277: directives target, teams), a 5.1 form NVHPC does not "
            "claim (rule R11c: unsupported, not a bug); its other diagnostic "
            "(S-0099 'Illegal use of derived type') follows."),
        "determinism": (
            "The diagnostic is the same in every compile. Whether the front end "
            "(fort2, fort1, nvcpfe) then dies with signal 11 varies from compile "
            "to compile of the same file in the same directory "
            "(data/evidence/gate_probe/logs/wingtip3.log: fixed paths, repeated); for "
            "nvcpfe long absolute source paths crash more often, a relative "
            "file name never did (0 of 80). No other condition was found: "
            "a compiler defect that shows intermittently."),
        "action": (
            "The cell counts as an ICE (the crash; the rejection is in every "
            "run). gang-dim: linked to the existing finding; ordered: promoted; "
            "the fuzz bundle: candidate, not reduced."),
        "counts_as": "failure",
    },
    "afar-hostdev-update": {
        "verdict": "nondeterministic_defect",
        "title": "AFAR: concurrent target update of disjoint sections from host threads loses data",
        "legality": (
            "Legal: four host threads each update their own disjoint section "
            "of a present array ('Assignment is performed to either the "
            "original or corresponding list item as specified with the "
            "specific data-motion clauses', 5.2 §5.9 p.165 l.7-12; 5.0 the "
            "same rule); the target regions write disjoint elements; i is "
            "private in the target region (5.2 §5.1.1 p.97 l.22-23). Read "
            "against the spec; the pre-run check's flang witness is AFAR's own "
            "front end, so it is not counted for the AFAR cells."),
        "determinism": (
            "A race inside the runtime, not in the program: the failure rate "
            "differs by device (MI300A copy mode: most runs fail; MI250X: "
            "rare)."),
        "action": "Linked to target-update-sections-in-parallel.f90 (its programs pattern already names omp5?-directive-target-hostdev); the cell counts as wrong_answer.",
        "finding": "target-update-sections-in-parallel.f90",
        "counts_as": "failure",
    },
    "stored-compile-timeout-load": {
        "verdict": "ours",
        "title": "The stored row is a compile timeout of one node at one moment; the program crashes in every rerun",
        "legality": (
            "The stored outcome (compile_timeout) is not a property of the "
            "program: the evidence campaign's only three AFAR compile timeouts "
            "are these, on one node (tuolumne2087) within one second "
            "(2026-10-23 13:11:44-45, results/confirm/evidence.jsonl), while "
            "the same variants built in 4-7 s and crashed (SIGSEGV) in the "
            "other memory mode on tuolumne1009 and 1028 that morning; AFAR "
            "builds them in 4-7 s in every rerun. Program 3 maps an "
            "absent optional dummy (zopt) in map clauses, which 5.2 §3.2.1 p.61 "
            "l.19-20 says is ignored; 4 and 5 pass offload.engine.rules (the flang "
            "witness is AFAR itself)."),
        "determinism": "The crash reproduces in every rerun (gate a-d, probe, gate runner at 1 and 24 workers).",
        "action": (
            "The stored class is a machine artefact: the cell counts as "
            "the reruns' crash. 3: related to "
            "catalog/afar-flang-absent-optional-target-crash.f90 (same "
            "feature; not reduced to it). 4, 5: crash candidates, unreduced."),
        "counts_as": "failure",
    },
    "afar-nested-firstprivate-xnack1": {
        "verdict": "environment_defect",
        "title": "AFAR loses the writes of a parallel region with firstprivate(i) nested in distribute; at XNACK 1 the stray stores corrupt host memory",
        "legality": (
            "Legal: firstprivate on a parallel construct nested in a distribute "
            "loop, of that loop's iteration variable, which is private in the "
            "teams region (5.2 §5.1.1 p.97 l.22-23; firstprivate: §5.4.4 "
            "p.112). The traces (data/evidence/gate_probe/checksum_trace.py: every checksum term "
            "against the same program's host runs on AFAR and CCE) show the "
            "array written in that kernel all zero, nothing else wrong."),
        "determinism": (
            "The lost writes are deterministic (the same wrong array in every "
            "run). At HSA_XNACK=1 the device's stores land in host memory; "
            "whether glibc then aborts (free(): invalid next size, corrupted "
            "size vs. prev_size) or the run prints the wrong value depends on "
            "the heap layout: the build path (b1:111: abort in the fuzz_ path, "
            "not in the GATE path), the runner and the node's load (06, 08: "
            "wrong value through the gate's own runner at 1 and 24 workers, "
            "abort in the gate's run). Condition: unified memory plus the "
            "process memory layout."),
        "action": "Linked to fuzz/650-afar.f90 (the minimized form); the cell counts as a wrong answer (abort and wrong value are the same defect).",
        "finding": "fuzz/650-afar.f90",
        "counts_as": "failure",
    },
    "afar-copy-reduction-varies": {
        "verdict": "nondeterministic_defect",
        "title": "AFAR copy mode: two do+simd reductions in parallel if(.false.) give varying values",
        "legality": (
            "Legal: reductions on a simd loop nested in a worksharing-loop "
            "reduction of the same variable (5.2 §5.5.8 p.134), in a parallel "
            "region with if(parallel: .false.). Read against the spec."),
        "determinism": (
            "r3a and r4a vary from run to run (traces), the rest is right. Five "
            "hand reproducers of the nested reduction pattern "
            "(data/evidence/gate_probe/simdred/) are correct on AFAR, so the trigger is "
            "not the nesting alone (r3a is integer(2), r4a reads an allocatable "
            "scalar and an assumed-shape array of derived type)."),
        "action": "Candidate, not reduced; the cell counts as wrong_answer.",
        "counts_as": "failure",
    },
    "cce-guarded-loop": {
        "verdict": "nondeterministic_defect",
        "title": "CCE: a loop guarded by omp_get_thread_num() == 0 (or omp_get_team_num() == 0) in a target region is wrong; a guarded scalar update varies",
        "legality": (
            "Legal: thread 0 alone executes the guarded loop "
            "(omp_get_thread_num 'returns the thread number of the calling "
            "thread, within the current team', 5.2 §18.2.4 p.351; "
            "omp_get_team_num, §18.4.2 p.373), so no element or scalar is "
            "written by two threads. The traces locate every wrong term in a "
            "guarded kernel's outputs (the guarded scalar and array), with the "
            "exceptions noted per entry."),
        "determinism": (
            "The guarded array stays zero in every run; the guarded scalar "
            "update (r = r + ..., ieor, ior) gives a different value from run "
            "to run in one build directory for 15 of the 18 programs (20, 37 and "
            "44 gave one value in each of their ten runs here; 20 and 44 "
            "disagree between the gate's a and d, 37 only with its stored row: "
            "per entry). A defect of the "
            "compiler, not of the program."),
        "action": "Linked to cce19-target-parallel-guarded-loop.f90 (the fuzz README lists the rediscoveries); the cell counts as wrong_answer.",
        "finding": "cce19-target-parallel-guarded-loop.f90",
        "counts_as": "failure",
    },
    "cce-lastprivate-distribute": {
        "verdict": "nondeterministic_defect",
        "title": "CCE: lastprivate on a composite distribute parallel do with num_threads (or if(parallel: .false.)) varies",
        "legality": (
            "Legal: the variable is assigned in every iteration, so 'the value "
            "of each new list item from the sequentially last iteration of the "
            "associated loops ... is assigned to the original list item' "
            "(5.2 §5.4.5 p.115 l.12-16); on a combined target construct it is "
            "also map(tofrom) (§17.2 p.340 l.27-30)."),
        "determinism": (
            "The traces locate the only wrong term in the lastprivate "
            "variable; its value varies between runs. Hand reproducers "
            "(data/evidence/gate_probe/lastprivate/): target teams distribute parallel "
            "do lastprivate(lp) num_threads(2) over 200 iterations gives lp= "
            "0, 61, 125 or 189 (10 runs each, CCE 19/20/21, XNACK 1 and 0); "
            "the same with if(parallel: .false.) and no num_threads, with "
            "collapse(2), with simd; without num_threads or if it gives 200 "
            "in every run (control). AFAR gives 200 on the simd form (it "
            "rejects lastprivate on the others: not implemented)."),
        "action": (
            "Linked to stress/cce-lastprivate-num-threads-collapse-simd.f90 "
            "(the same defect: its header's trigger is narrower than these "
            "reproducers show; collapse and simd are not "
            "needed, and if(parallel: .false.) triggers it without "
            "num_threads). The cell counts as wrong_answer."),
        "finding": "stress/cce-lastprivate-num-threads-collapse-simd.f90",
        "counts_as": "failure",
    },
    "cce-crash-or-hang": {
        "verdict": "nondeterministic_defect",
        "title": "CCE: the program fails in every run; whether it aborts or hangs varies within one directory",
        "legality": (
            "No construct the pre-run check or a reading of the failing kernel "
            "found illegal; AFAR (and CCE 21 where it compiles them) prints "
            "the generator's value on the same programs."),
        "determinism": "Every run fails; in one build directory the form varies (GPU memory access fault and SIGABRT 7 times, a hang to the limit 3 times in 10 runs).",
        "action": "Candidates (confirmer compiler_bug, no finding); the cell counts as a crash.",
        "counts_as": "failure",
    },
    "cce-mapper-present-table": {
        "verdict": "nondeterministic_defect",
        "title": "CCE 19 unified: a named declare mapper's member is 'not found in present table'",
        "legality": (
            "Legal: map(mapper(mmap), ...) with a module declare mapper "
            "mapping v%a of a fixed-size component (5.2 §5.8.8 p.162); the "
            "structure is present (target data) or mapped on the construct. "
            "CCE 21 prints the generator's value on the original programs "
            "(fuzz s1:7606, s1:2529); AFAR crashes on them too (another "
            "failure, not studied)."),
        "determinism": "Every run fails with CRAY_ACC_ERROR 'Variable not found in present table' for 'v(:)'; the process then exits 1 or aborts after a GPU memory fault, which varies.",
        "action": "Candidate, not reduced; the cell counts as a run error.",
        "counts_as": "failure",
    },
    "cce-1505-xnack1": {
        "verdict": "environment_defect",
        "title": "CCE 19/20: the o3 writes of the c1:1505 kernel are lost; at XNACK 1 the stray stores corrupt the host heap",
        "legality": (
            "Legal per the finding's reading (fuzz/1505-cce20.f90, the same "
            "seed's kernel 3). The traces: o3 all zero, nothing else wrong."),
        "determinism": "The lost o3 is deterministic; the process then aborts (munmap_chunk, corrupted size) or not depending on the heap layout (the instrumented build aborts, the plain one prints the value), as the stored SIGSEGV/SIGABRT rows did.",
        "action": "Linked to fuzz/1505-cce20.f90; the cell counts as wrong_answer.",
        "finding": "fuzz/1505-cce20.f90",
        "counts_as": "failure",
    },
    "cce-char-map-ice-message": {
        "verdict": "environment_defect",
        "title": "CCE: the character-scalar map ICE gives one of three messages, depending on the build path",
        "legality": (
            "Legal: a character scalar is a variable list item of map (5.2 "
            "§3.2.1 p.60; §5.8.3), as the finding reads it."),
        "determinism": (
            "Every compile is an ICE. Which internal check fires ('Unhandled "
            "expression type in get base or dv mem', 'unexpected type in "
            "TYPE_DEREF', or optcg signal 11) depends on the build path: a "
            "sweep of ten directory-name lengths gives one message for most "
            "lengths and another (or the optcg crash) for one or two, a "
            "different length for each program; the gate's reruns at two "
            "paths of equal length (a and c) agreed."),
        "action": (
            "Linked to fuzz/s1-8634-cce21.f90, whose index message already "
            "matches all three. The gate called it environment only because "
            "its ICE comparison keys on the message (a gate change for the "
            "controller: two ICEs whose messages one finding's pattern "
            "matches are the same failure). The cell counts as an ICE."),
        "finding": "fuzz/s1-8634-cce21.f90",
        "counts_as": "failure",
    },
    "not-reproduced-once": {
        "verdict": "undecided",
        "title": "The stored failure did not recur",
        "legality": "No illegal construct found by the pre-run check; the programs of 25 and 2 were read (legal, per entry).",
        "determinism": "The stored session failed (how often: per entry); none of the reruns did: the gate's four, ten probe runs, and 120 (entry 25: 168) through the gate's own runner, half of them at 24 concurrent reruns per node (the gate's load): 0 failures in at least 134 runs per entry (entry 2: 54 runs on MI250X). A defect, if any, needs a condition these reruns lacked.",
        "action": "Not counted (the gate already does not count it). What would decide it: per entry.",
        "counts_as": "none",
    },
    "capacity-large-args": {
        "verdict": "unspecified",
        "title": "CCE runtime capacity: 'CRAY_ACC_ERROR - Large args not supported'",
        "legality": (
            "The program is conforming but exceeds a capacity of the "
            "implementation (a kernel with hundreds of mapped arrays, "
            "reduction or shared scalars). Neither OpenMP nor OpenACC sets a "
            "limit, and the base language leaves capacity to the processor "
            "(Fortran 2008, ISO/IEC 1539-1:2010 §1.1: the standard does not "
            "specify 'the size or complexity of a program and its data that "
            "will exceed the capacity of any particular computing system or "
            "the capability of a particular processor'; quoted from the "
            "standard, which results/spec_cache does not hold). The stress campaign "
            "already counts these as break points (data/reports/fuzz-stress.md, "
            "Capacity)."),
        "determinism": (
            "At low load (6 concurrent runs per node) every run exits 1 with the "
            "message (six runs per cell in the gate's paths a and b), though "
            "not uniformly fast (59: 19.6 s and 62.4 s, 67: 42.8 s and 16.1 s, "
            "against about 3 s). That the gate's timeouts in b and c came from "
            "its 24 concurrent reruns per node is an inference: these rows were "
            "not rerun at that load."),
        "action": (
            "The row stops counting as a compiler failure (a capacity break "
            "point). No generator change: the stress axes exist to find break "
            "points and the stress report keeps them in its break-point table."),
        "counts_as": "none",
    },
    "capacity-microtask-args": {
        "verdict": "unspecified",
        "title": "AFAR runtime capacity: 'Too many arguments in kmp_invoke_microtask, aborting execution'",
        "legality": (
            "Conforming C (64 to 1,024 reduction scalars on target teams "
            "distribute parallel for; 5.2 §17.2 p.340), beyond the device "
            "runtime's limit on the outlined function's arguments, which it "
            "reports; capacity is the processor's (C18, ISO/IEC 9899:2018 §1 "
            "para. 2: the standard does not specify 'the size or complexity "
            "of a program and its data that will exceed the capacity of any "
            "specific data-processing system'; not in results/spec_cache)."),
        "determinism": "Every run fails with the message; after it the kernel traps, and the process then usually hangs to the limit instead of ending: in one build directory each, 63: 5 of 6 runs hang, 66: 5 of 6, 64: 2 of 6, 65: 2 of 6 (the rest abort); the gate's reruns: 63 4 of 4 hang. The break point (C int64 sum reductions on target teams distribute parallel for, data/evidence/gate_probe/reduce/red_c_N.c, every size from 8 to 64, two runs each): 62 scalars work, from 63 on the kernel traps and the process aborts (in the reduced program the message is not printed and nothing hangs within 30 s; the stress kernel prints it and mostly hangs).",
        "action": "The row stops counting as a compiler failure (a capacity break point, now in data/reports/fuzz-stress.md's capacity table with its break point). A quality-of-implementation candidate (lower tier) is recorded: the runtime prints 'aborting execution' and then hangs instead of ending the process (rates above).",
        "counts_as": "none",
    },
    "compile-time-limit": {
        "verdict": "ours",
        "title": "A compile near the 900 s limit",
        "legality": "Conforming (1,720 OpenACC kernels in one program); a compile time is not a conformance property.",
        "determinism": "The compile ends within 900 s in three of the gate's four environments and took 1,606 s here (two such compiles at once on one node, both modes, then a correct run: checksum 441727146 as expected); its time depends on the node's load.",
        "action": "Harness limit, not a compiler failure: the row stops counting; the stress report treats a timeout as a break point only when a smaller sibling fit (it does).",
        "counts_as": "none",
    },
    "cce-lastprivate-stress": {
        "verdict": "nondeterministic_defect",
        "title": "CCE: the 14-clause stress program's lastprivate (the program the finding was reduced from)",
        "legality": "Legal (5.2 §5.4.5 p.115, §17.2 p.340 l.27-30; lin is private since stress).",
        "determinism": "lp is right in some runs and off by 1 to 3 in others (checksum 50690-50692 for 50693). In one build directory: CCE 19 copy 3 of 20 wrong, CCE 21 copy 1 of 20, CCE 20 unified 20 of 20 wrong with one value (50692; the gate saw 50690 too), CCE 20 copy 0 of 20 (the gate saw one wrong run in four).",
        "action": "Linked to stress/cce-lastprivate-num-threads-collapse-simd.f90; the cell counts as wrong_answer.",
        "finding": "stress/cce-lastprivate-num-threads-collapse-simd.f90",
        "counts_as": "failure",
    },
    "stress-load-timeout": {
        "verdict": "ours",
        "title": "A deterministic wrong answer; the gate's disagreement was a run timeout under load",
        "legality": "Legal for its version (the stress generator's model; the routes are read in data/reports/fuzz-stress.md).",
        "determinism": "Every completed run gives the same wrong value; the gate saw a run timeout (or a timed-out internal repeat) in one environment, under 24 concurrent reruns per node.",
        "action": "The timeout is the machine's load: the cell counts as its wrong answer (confirmed).",
        "counts_as": "failure",
    },
    "stress-alloc-2e32": {
        "verdict": "nondeterministic_defect",
        "title": "CCE: fill and reduce a 2^32-element integer(8) allocatable",
        "legality": "Conforming (integer(8) indices and extents); 32 GiB on the host and on the device of a 128 GB MI300A.",
        "determinism": "CCE 20 copy mode: a GPU memory access fault in every run (7 of 7). CCE 21 unified: wrong in every run; the value is 2147378998 in the stored run, the gate's a and d and three probe runs, and other values in the gate's b and c (recorded in data/reports/fuzz-stress.md as the CCE 21 alloc case, not reduced).",
        "action": "Reduced (data/evidence/gate_probe/reduce/alloc_*.f90, fill_check_32.f90, hostfill_reduce_32.f90): on CCE 21 the fill loop over 2**32 iterations skips its last 256 iterations (wrong= 256), the reduction is right, 2**31 is right, AFAR and nvfortran are right: promoted, data/findings/cce21-alloc-2e32-sum-wrong.f90. CCE 19/20 fault at 2**32 (both modes; CCE 20 in the fill loop alone) and do not finish 2**31 in 300 s; recorded in that finding, not claimed. The cell counts as its failure.",
        "counts_as": "failure",
    },
    "cce-acc-reduction-200": {
        "verdict": "nondeterministic_defect",
        "title": "CCE 20/21 OpenACC: 200 reduction scalars on a parallel loop give wrong, varying values",
        "legality": (
            "Legal: reduction on a combined parallel loop 'implies a copy "
            "clause' for each variable (OpenACC 3.4 §2.11 p.76 l.2790-2792; "
            "§2.9.11). The OpenMP form of the same program ends with the "
            "capacity message instead (capacity-large-args): here the result "
            "is silently wrong, which a capacity limit does not excuse."),
        "determinism": "The values of the reductions past about the hundredth vary from run to run; some runs hang to the limit (CCE 20 copy mode in the gate).",
        "action": "Reduced and promoted: data/findings/cce-acc-reduction-200-int8-scalars-wrong.f90 (the trigger is 200 integer(8) reductions: 175 right, default-kind integers right at 200; CCE 19 and NVHPC right). The cell counts as wrong_answer.",
        "finding": "cce-acc-reduction-200-int8-scalars-wrong.f90",
        "counts_as": "failure",
    },
    "cce-acc-allocate-path": {
        "verdict": "environment_defect",
        "title": "CCE 19/20 OpenACC: ALLOCATE in a compute region fails; exit 1 or SIGABRT by build path",
        "legality": "Legal (OpenACC 3.4 §1.8 p.16: Fortran 2008 is a normative base language; ALLOCATE is not among the features it lists as unspecified), as the finding reads it.",
        "determinism": "Every run fails; the form (exit 1 or SIGABRT) is fixed per build directory and differs between directories.",
        "action": "Linked to catalog/cce-acc-allocate-in-compute-crash.f90 (kept it); the cell counts as a run failure.",
        "finding": "catalog/cce-acc-allocate-in-compute-crash.f90",
        "counts_as": "failure",
    },
}

# queue index -> (group, per-entry note)
ASSIGN = {
    0: ("nvhpc-postdiag-crash", "fort2 after S-0155: crashed in 152 of 152 compiles in this task (wingtip1 40/40, wingtip2 32/32, wingtip3 80/80) and in the gate's 4 of 4; only the stored row (an earlier session) did not: the stored outlier is unexplained; existing finding"),
    53: ("nvhpc-postdiag-crash", "fort1 after S-0533/S-0099: crashed in 93 of 107 compiles (wingtip1 35/40, wingtip2 27/32, wingtip3 28/30, the gate 3/4, the stored row 0/1, though its log has the crash line); at one fixed path it crashed in 4 of 5 (two paths) or 5 of 5"),
    95: ("nvhpc-postdiag-crash", "nvcpfe 26.9: crashed in 31 of 58 compiles by absolute path"),
    96: ("nvhpc-postdiag-crash", "nvcpfe 25.11 managed: crashed in 26 of 52 compiles by absolute path"),
    1: ("afar-hostdev-update", "MI300A copy mode"),
    2: ("not-reproduced-once", "MI250X, the omp50 form: the stored run failed (check=fail); 0 of 54 reruns did (Tioga 50 in two directories, the gate's 4). The omp52 form on MI250X failed 1 in 25 (a memory fault): the finding's defect shows on MI250X, but this cell's failure did not recur. Legal (read: as entry 1). Decider: a larger repeat on MI250X"),
    3: ("stored-compile-timeout-load", "AFAR 'Failure to allocate device memory: out of resources' then SIGABRT; maps the absent optional zopt"),
    4: ("stored-compile-timeout-load", "SIGSEGV"),
    5: ("stored-compile-timeout-load", "SIGSEGV"),
    6: ("afar-nested-firstprivate-xnack1", "o2 lost"),
    7: ("afar-nested-firstprivate-xnack1", "o2 and r2a lost; free(): invalid next size after the value"),
    8: ("afar-nested-firstprivate-xnack1", "o2 lost"),
    26: ("afar-nested-firstprivate-xnack1", "o1 and r1a lost; free(): invalid next size"),
    27: ("afar-nested-firstprivate-xnack1", "o1 and r1a lost"),
    28: ("afar-nested-firstprivate-xnack1", "abort (corrupted size vs. prev_size) in the fuzz_ path only"),
    33: ("afar-nested-firstprivate-xnack1", "o2 wrong, its values vary between runs"),
    34: ("afar-nested-firstprivate-xnack1", "o2 lost; corrupted size vs. prev_size"),
    14: ("afar-copy-reduction-varies", "r3a (integer(2) ieor) sometimes lost, r4a (+) varies"),
    9: ("cce-guarded-loop", "par_thread0 (r1a, o1) and teams_team0 (o3)"),
    12: ("cce-guarded-loop", "par_thread0 (r1a, o1)"),
    17: ("cce-guarded-loop", "par_thread0 (r1a, o1)"),
    18: ("cce-guarded-loop", "par_thread0 (r1a, o1)"),
    21: ("cce-guarded-loop", "par_thread0 (r1a, o1)"),
    19: ("cce-guarded-loop", "par_thread0 (r3a, o3); o4 of the in_reduction kernel is o4(i) = iand(o3(101 - i), 65535), so it inherits the guarded o3 (read: the in_reduction kernel is legal, 5.2 §5.5.10; its r4a is right)"),
    20: ("cce-guarded-loop", "par_thread0 (r1a, o1); r3a and o3 of the teams distribute parallel do kernel are computed from o1 (r3a = max(r3a, o1(i)*5), o3 from ishft(o1(i))), so they inherit the guarded o1 (read: legal; r3b, which does not read the guarded output's wrong elements, is right)"),
    36: ("cce-guarded-loop", "par_thread0 (r1a)"),
    37: ("cce-guarded-loop", "par_thread0 (r1a, o1)"),
    39: ("cce-guarded-loop", "par_thread0 (r1a, o1)"),
    40: ("cce-guarded-loop", "par_thread0 (r2a, o2)"),
    41: ("cce-guarded-loop", "par_thread0 and split_par_thread0 (r1a, ds%o1, go2)"),
    44: ("cce-guarded-loop", "par_thread0 (r1a, o1)"),
    46: ("cce-guarded-loop", "par_thread0 (r1a)"),
    47: ("cce-guarded-loop", "par_thread0 (r1a, o1)"),
    49: ("cce-guarded-loop", "par_thread0 (r3a, o3)"),
    51: ("cce-guarded-loop", "par_thread0 (r3a, o3)"),
    52: ("cce-guarded-loop", "par_thread0 (o2, r2a), teams_team0 (r3a, o3); the fourth kernel (a sequential loop in a plain target with firstprivate(p2), real(8) outputs o4 and r4a, inputs ib and p2 only) is wrong too and is not explained by a guard: read, legal (p2 firstprivate, 5.2 §5.4.4; o4 map(from), r4a map(always, tofrom)); a separate candidate, not reduced"),
    22: ("cce-lastprivate-distribute", "lp2: distribute parallel do num_threads(8)"),
    23: ("cce-lastprivate-distribute", "lp2: distribute parallel do num_threads(8)"),
    24: ("cce-lastprivate-distribute", "lp1: teams distribute parallel do collapse(2) num_threads(2)"),
    38: ("cce-lastprivate-distribute", "lp4: distribute parallel do if(parallel: .false.) with a nested simd lastprivate"),
    42: ("cce-lastprivate-distribute", "lp4: distribute parallel do num_threads(2) with a nested simd lastprivate"),
    43: ("cce-lastprivate-distribute", "lp4: as s1x0:1012"),
    45: ("cce-lastprivate-distribute", "lp4: as b4:253"),
    50: ("cce-lastprivate-distribute", "lp1: teams distribute parallel do num_threads(2) if(parallel: .false.)"),
    10: ("cce-crash-or-hang", "fuzz s1:12 (num_teams(1) variant): memory access fault at address (nil); CCE 19/20 crash, AFAR and CCE 21 correct"),
    11: ("cce-crash-or-hang", "fuzz s1:5308: memory access fault or hang; the stored row a timeout"),
    35: ("cce-crash-or-hang", "fuzz s1:1127: memory access fault; AFAR and CCE 21 correct"),
    48: ("cce-crash-or-hang", "fuzz x0-alloc:197: 'Unhandled Reduction!!!' then a memory access fault. Reduced (kernels removed one at a time, data/evidence/gate_probe/logs/reduce.txt): the fault needs kernel 4 alone, a target in_reduction in a taskgroup task_reduction inside a procedure that maps assumed-shape dummy arrays; with explicit-shape dummies or without in_reduction it is right (CCE 19, 20), and removing the region's write of the host-associated hf4 or its indexed read of the inout dummy o3 also makes it right; the message needs kernels 1, 2 and 4 together. Short programs of that pattern (data/evidence/gate_probe/reduce/inred_*.f90) do not crash CCE 19/20, so the crash is not reduced further; they showed a CCE 21 defect instead, promoted: data/findings/cce21-in-reduction-assumed-shape-write-lost.f90"),
    15: ("cce-mapper-present-table", "fuzz s1:7606 schedule_static_1 variant"),
    16: ("cce-mapper-present-table", "fuzz s1:2529 thread_limit_32 variant"),
    29: ("cce-1505-xnack1", "CCE 19"),
    30: ("cce-1505-xnack1", "CCE 20"),
    13: ("cce-char-map-ice-message", "CCE 21"),
    31: ("cce-char-map-ice-message", "CCE 20"),
    32: ("cce-char-map-ice-message", "CCE 21"),
    25: ("not-reproduced-once", "CCE 20 unified: the stored run crashed once (SIGSEGV, tuolumne1025, 2026-10-23 10:12:49); 0 of 168 reruns. The same program crashed on AFAR unified on that node 6 s earlier (10:12:43), and AFAR crashes on it here too (2 of 2 SIGSEGV): an AFAR failure of this legal program (read: n = nm = 16, so go1(1:n) and go1(:) name the same storage and the four nowait tasks' depend chain is ordered), recorded, not studied. Decider for CCE 20: tuolumne1025's GPU log at 10:12"),
    54: ("not-reproduced-once", "AFAR unified (fuzz b2 seed 121, base 'derived 121'): the stored session crashed in both of its runs (with and without OMP_TARGET_OFFLOAD=mandatory) with AFAR's common HSA_XNACK=1 fault (write to a read-only page at 0x555500000000, 80 times in campaign s1 alone, so not a sign of the node). data/reports/fuzz-base-language.md:133 already classed this seed load_or_flake: correct on idle nodes with THP on and with THP off. Lead: the b sessions ran on the loaded interactive node tuolumne2151 with THP never, the gate with THP always; the reviewer's THP-never rerun of 54-56 (tuolumne1010, 60 of 60 correct) rules THP alone out. Decider: tuolumne2151's GPU log for 2026-10-21"),
    55: ("not-reproduced-once", "AFAR unified (fuzz b3 seed 142): the stored session crashed in both of its runs with the same 0x555500000000 fault. Lead and decider as for 54 (THP never on tuolumne2151 in the b sessions; THP never alone ruled out by the reviewer's 60 of 60)"),
    56: ("not-reproduced-once", "AFAR unified (fuzz b4 seed 209): the stored row is flaky: 4 of 4 repeats wrong, each with another value (27423373, 241716955, 101358633, 1898795605). Lead and decider as for 54"),
    57: ("capacity-large-args", "310 mapped arrays (OpenACC)"),
    58: ("capacity-large-args", "256 mixed clauses (OpenACC)"),
    59: ("capacity-large-args", "1,024 lastprivate scalars"),
    60: ("capacity-large-args", "310 mapped arrays (OpenACC)"),
    61: ("capacity-large-args", "256 mixed clauses (OpenACC)"),
    67: ("capacity-large-args", "200 reduction scalars (OpenMP)"),
    76: ("capacity-large-args", "256 reduction scalars (OpenACC)"),
    77: ("capacity-large-args", "1,024 shared scalars (OpenACC)"),
    83: ("capacity-large-args", "200 reduction scalars (OpenMP)"),
    63: ("capacity-microtask-args", "64 reductions; the QoI candidate: after the message the process hangs to the limit in 5 of 6 runs here and 4 of 4 in the gate"),
    64: ("capacity-microtask-args", "1,024 reductions; hangs in 2 of 6 runs here (the rest abort)"),
    65: ("capacity-microtask-args", "1,024 reductions, XNACK 1; hangs in 2 of 6 runs here"),
    66: ("capacity-microtask-args", "256 reductions; hangs in 5 of 6 runs here"),
    62: ("compile-time-limit", "CCE 21 copy"),
    84: ("compile-time-limit", "CCE 21 unified"),
    68: ("cce-lastprivate-stress", "CCE 19 copy"),
    78: ("cce-lastprivate-stress", "CCE 20 unified"),
    79: ("cce-lastprivate-stress", "CCE 20 copy"),
    85: ("cce-lastprivate-stress", "CCE 21 copy"),
    69: ("stress-load-timeout", "num_teams(4194304) reduction: stress/cce-teams-reduction-many-teams-wrap.f90"),
    80: ("stress-load-timeout", "OpenACC num_gangs(4194304) reduction: the OpenACC form of the teams wrap (related to stress/cce-teams-reduction-many-teams-wrap.f90)"),
    70: ("stress-load-timeout", "OpenACC alloc shape at 2^30 (CCE 19/20 wrong from 2^22; recorded in data/reports/fuzz-stress.md, not promoted)"),
    71: ("stress-load-timeout", "OpenACC declare create scalars: stress/cce-acc-declare-create-scalar-serial-firstprivate.f90"),
    73: ("stress-load-timeout", "OpenACC declare create scalars: stress/cce-acc-declare-create-scalar-serial-firstprivate.f90"),
    74: ("stress-load-timeout", "OpenACC declare create scalars: stress/cce-acc-declare-create-scalar-serial-firstprivate.f90"),
    87: ("stress-load-timeout", "OpenACC declare create scalars: stress/cce-acc-declare-create-scalar-serial-firstprivate.f90"),
    89: ("stress-load-timeout", "OpenACC declare create scalars: stress/cce-acc-declare-create-scalar-serial-firstprivate.f90"),
    72: ("stress-load-timeout", "C: 64 reduction scalars on target teams distribute parallel for (kernel k0012) give one wrong value; reduced and promoted: data/findings/cce19-c-reduction-63-scalars-one-wrong.c (CCE 19 from 63 scalars; 62 right; CCE 20/21, nvc right)"),
    75: ("stress-alloc-2e32", "CCE 20 copy: memory access fault"),
    86: ("stress-alloc-2e32", "CCE 21 unified: wrong, varying"),
    81: ("cce-acc-reduction-200", "CCE 20 unified"),
    82: ("cce-acc-reduction-200", "CCE 20 copy"),
    88: ("cce-acc-reduction-200", "CCE 21 unified"),
    90: ("cce-acc-reduction-200", "CCE 21 copy"),
    91: ("cce-acc-allocate-path", "CCE 19 copy"),
    92: ("cce-acc-allocate-path", "CCE 19 unified"),
    93: ("cce-acc-allocate-path", "CCE 20 copy"),
    94: ("cce-acc-allocate-path", "CCE 20 unified"),
}

# what repeats in one environment showed where the probe did not repeat
# runs (compile-only entries: wingtip fixed-path repeats; the character-map
# ICE: the gate's a and d)
ONE_ENV = {
    0: "nvfortran 25.11: 40 compiles at two fixed directory names (20 each) all crashed; 80 lengths, all crashed (data/evidence/gate_probe/logs/wingtip1.log, wingtip3.log)",
    53: "nvfortran 26.9: at six fixed paths, 5 compiles each: 4 of 5 crashed at two of them, 5 of 5 at four (wingtip3.log): the same path disagrees with itself",
    95: "nvc 26.9 separate: at a 37-character directory 1 of 3 crashed (the same path disagrees with itself); at 17 characters 3 of 3; at 1, 9, 45 0 of 3 (wingtip3.log); a 45/84-character pair: 0/3 and 2/3 (wingtip4.log)",
    96: "nvc 25.11 managed: at a fixed path of 45 characters 1 of 3 crashed (wingtip4.log): the same path disagrees with itself; at 33 characters 3 of 3, at 1 and 3 characters 0 of 3 (wingtip3.log)",
    13: "ICE in every compile; the gate's a and d (same path) agreed; ten other path lengths gave the message per length (data/evidence/gate_probe/logs/ice_paths.txt)",
    31: "ICE in every compile; the gate's a and d (same path) agreed; ten other path lengths gave the message per length (ice_paths.txt)",
    32: "ICE in every compile; the gate's a and d (same path) agreed; ten other path lengths gave the message per length (ice_paths.txt)",
}

# per-entry verdicts that differ from the group's (fix, I2: each
# entry is decided on its own evidence), with the reason
OVERRIDE = {
    0: ("environment_defect", "failure", "provisional: every rerun crashes (152 of 152 here, 4 of 4 in the gate); only the stored row of an earlier session did not, with no condition found"),
    37: ("environment_defect", "failure", "provisional: every rerun gives one value (1256234274: the gate's four, ten here); only the stored row of an earlier session differs"),
    10: ("ours", "failure", "a deterministic crash: SIGABRT in 10 of 10 runs in each of two directories and in the gate's a, b, d; the one variation is the gate's c, a run timeout under its load"),
    35: ("ours", "failure", "a deterministic crash: SIGABRT in every stored, gate and probe run; the one variation is one internal repeat of the gate's d that timed out at 24 workers (results/gate/fuzz/reruns/tuolumne1027.abd.*)"),
    48: ("ours", "failure", "a deterministic crash ('Unhandled Reduction!!!', then a memory fault) in every stored, gate and probe run; the one variation is one internal repeat of the gate's d that timed out at 24 workers"),
    75: ("ours", "failure", "a deterministic crash: a GPU memory access fault in 7 of 7 runs here and in all four gate reruns; the gate's 'nondeterministic' came from internal repeats under its load"),
    33: ("nondeterministic_defect", "failure", "the values vary within one build directory (305017827 x4, 1092538165 x1), so not an environment"),
}
# the stated basis of a nondeterministic verdict whose probe directories
# each agreed with themselves
BASIS = {
    15: "the gate's a and d (one path, one node) disagree: exit 1 against SIGSEGV",
    20: "the gate's a and d disagree (189757324 against 524644241)",
    44: "the gate's a and d disagree (1386972515 against 1256234274)",
    78: "the gate's a and d disagree (50690 against 50692)",
    79: "the stored row's own repeats disagree (flaky); the gate's c wrong, a, b, d right",
    86: "the gate's b disagrees with itself (its internal repeats; 2083783878 and others)",
}

LINKS = {  # per-entry finding links where the group has none
    3: "catalog/afar-flang-absent-optional-target-crash.f90 (related)",
    69: "stress/cce-teams-reduction-many-teams-wrap.f90",
    80: "stress/cce-teams-reduction-many-teams-wrap.f90 (related)",
    71: "stress/cce-acc-declare-create-scalar-serial-firstprivate.f90",
    73: "stress/cce-acc-declare-create-scalar-serial-firstprivate.f90",
    74: "stress/cce-acc-declare-create-scalar-serial-firstprivate.f90",
    87: "stress/cce-acc-declare-create-scalar-serial-firstprivate.f90",
    89: "stress/cce-acc-declare-create-scalar-serial-firstprivate.f90",
    0: "nvhpc-acc-atomic-update-sum-fort2-crash.f90",
    95: "nvhpc-c-ordered-in-target-nvcpfe-crash.c (new)",
    72: "cce19-c-reduction-63-scalars-one-wrong.c (new)",
    86: "cce21-alloc-2e32-sum-wrong.f90 (new)",
    75: "cce21-alloc-2e32-sum-wrong.f90 (related: the same program; CCE 20's fault is recorded there, not claimed)",
    48: "cce21-in-reduction-assumed-shape-write-lost.f90 (related: found while reducing it)",
    96: "nvhpc-c-ordered-in-target-nvcpfe-crash.c (new)",
}


def tioga_counts() -> Counter:
    out = Counter()
    if TIOGA.is_file():
        for ln in TIOGA.read_text().splitlines():
            d = json.loads(ln)
            if d.get("step") == "run" and d["id"] == "02/orig":
                out[O.classify(d, None)] += 1
    return out


FROZEN = ("stored", "gate_reruns", "probe_runs", "within_one_environment",
          "gate_runner_low_load", "gate_runner_gate_load")


def refresh_frozen() -> int:
    """After regenerated the gate (its queue is no
    longer these 97 rows), the observations of each row are kept as
    recorded in catalog/gate_queue.yaml and only the decisions (groups,
    overrides, links, notes) are rewritten from the tables above."""
    out = ROOT / "catalog" / "gate_queue.yaml"
    old = yaml.safe_load(out.read_text())
    entries = []
    for e in old["entries"]:
        k = e["k"]
        g, note = ASSIGN[k]
        grp = GROUPS[g]
        verdict, counts_as, why = OVERRIDE.get(
            k, (grp["verdict"], grp["counts_as"], ""))
        new = {key: e[key] for key in ("k", "cell", "campaign", "toolchain",
                                       "mode", "gate_verdict")}
        new.update({"group": g, "verdict": verdict, "counts_as": counts_as,
                    "verdict_reason": why or f"the group's ({g})",
                    "nondeterminism_basis": BASIS.get(k, ""),
                    "finding": LINKS.get(k) or grp.get("finding", ""),
                    "note": note})
        new.update({key: e[key] for key in FROZEN})
        entries.append(new)
    return write(entries)


def main() -> int:
    from offload.engine import gate as G
    from offload.engine import gate_report as GP
    q = J.queue()
    if len(q) != 97:
        return refresh_frozen()
    reruns = {}
    for c in sorted({r["campaign"] for r, _ in q}):
        reruns.update(GP._reruns(c))
    assert len(q) == 97, len(q)
    assert set(ASSIGN) == set(range(97)), sorted(set(range(97)) - set(ASSIGN))
    entries = []
    for k, (rec, item) in enumerate(q):
        g, note = ASSIGN[k]
        grp = GROUPS[g]
        verdict, counts_as, why = OVERRIDE.get(
            k, (grp["verdict"], grp["counts_as"], ""))
        exp = O.expected_of(rec, item)
        probe = O.probe_counts([p for p in PROBES
                                if (p, k) not in NOT_EVIDENCE], k, exp)
        if k == 2:
            probe = tioga_counts()
        one_env = O.within_one_environment(
            [p for p in PROBES if (p, k) not in NOT_EVIDENCE], k, exp) \
            or ONE_ENV.get(k, "")
        if k == 2:
            one_env = O.within_one_environment([TIOGA], k, None)
        low = O.gate_rerun_counts(GATE_RERUNS["low"], k)
        high = O.gate_rerun_counts(GATE_RERUNS["high"], k)
        gate = [f"{r['env']}: {'|'.join(G.observe(r))[:70]}" for r in
                reruns.get(rec["cell"], [])]
        entries.append({
            "k": k, "cell": rec["cell"], "campaign": rec["campaign"],
            "toolchain": rec["toolchain"], "mode": rec["mode"],
            "gate_verdict": rec["verdict"], "group": g,
            "verdict": verdict, "counts_as": counts_as,
            "verdict_reason": why or f"the group's ({g})",
            "nondeterminism_basis": BASIS.get(k, ""),
            "finding": LINKS.get(k) or grp.get("finding", ""),
            "note": note, "stored": rec["original"][:120],
            "gate_reruns": gate,
            "probe_runs": dict(probe),
            "within_one_environment": one_env,
            "gate_runner_low_load": dict(low),
            "gate_runner_gate_load": dict(high)})
    return write(entries)


def write(entries: list) -> int:
    doc = {"version": 1, "task": 48, "date": "2026-10-26",
           "source": ("the gate review queue (97 rerun rows) as of 65a85ca; "
                      "(6d3438a) regenerated the gate and attached "
                      "these decisions by row"),
           "verdicts": list(VERDICTS),
           "groups": [{"id": g, **v} for g, v in GROUPS.items()],
           "entries": entries}
    out = ROOT / "catalog" / "gate_queue.yaml"
    head = ("# Decisions on the reproduction gate's review queue "
            ".\n# Generated by data/evidence/gate_probe/"
            "build_queue.py from its decision table and the probe runs "
            "(results/t48/);\n# rendered by data/evidence/gate_probe/gate_queue.py "
            "into data/reports/gate-queue.md.\n"
            "# A decision applies to its own row (cell) only and never "
            "propagates to the rows that\n# inherit the gate verdict of its "
            "signature (maintainer's ruling, run-time\n"
            "# failures never inherit).\n")
    out.write_text(head + yaml.safe_dump(doc, sort_keys=False, width=100,
                                         allow_unicode=True))
    print(Counter(e["verdict"] for e in entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
