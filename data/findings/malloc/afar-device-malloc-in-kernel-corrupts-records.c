// # Finding (kernel-body campaign): AFAR on MI300A: free() in a kernel appears not to release the caller's stores to the block
// # before it can be handed out again, so records written through malloc'd temporaries come out wrong (HSA_XNACK=1)
//
// - toolchains and modes that fail: afar (AFAR 24.3.0); modes: unified; -O2
// - build: amdclang -fopenmp --offload-arch=gfx942 -fopenmp-version=52 -O2
// - failure: wrong_answer (check=fail)
// - observed: `cells 47916000 ghost 47916000`; identical signature on 2 of 2 failing cells (the second, in copy mode, failed
//   1 of 10 harness repeats and was correct in all four gate environments)
// - expected: compiles and runs to completion, printing `RESULT ran_on_host=0 check=pass`
// - rule: implementation contract (no OpenMP rule), not a specification violation: a target region is executed by an initial
//   thread on the device, "sequentially, as if the target region is part of an initial task region" (5.2 §1.3 p.24 l.10-11),
//   and "The implementation must ensure that the target region executes as if it were executed in the data environment of the
//   target device" (5.2 §1.3 p.24 l.15-16), which fix the execution model of the target region and say nothing about library
//   calls on the device; the body of each iteration is ordinary C (malloc, store, memcpy, free of a block the iteration owns,
//   a store to an element only that iteration writes). The OpenMP text has no sentence about malloc in a target region; that
//   malloc works in a target region is the base language's and the implementation's contract, and a program that is correct
//   on the host and on CCE 21 must not change its records on one device
// - same-compiler control: controls/afar-first-use-malloc-direct.c (one change from this file; correct on afar (AFAR 24.3.0);
//   rows results/malloc-dd/finding_rows.jsonl, results/malloc-dd/finding_rows.jsonl); controls/afar-first-use-malloc-stack.c
//   (one change from this file; correct on afar (AFAR 24.3.0); rows results/malloc-dd/finding_rows.jsonl);
//   controls/afar-first-use-malloc-fence.c (one change from the 56-line text of the reduction, not from this file: a
//   device-scope release fence, `__scoped_atomic_thread_fence(__ATOMIC_RELEASE, __MEMORY_SCOPE_DEVICE)`, between the memcpy
//   and free; correct on afar (AFAR 24.3.0); rows results/malloc-dd/finding_rows.jsonl);
//   controls/afar-first-use-malloc-flush.c (one change from the 56-line text, not from this file: `#pragma omp flush` between
//   the memcpy and free; correct on afar (AFAR 24.3.0); rows results/malloc-dd/finding_rows.jsonl)
// - which text ran: the harness rows, the gate rows and the launch counts of rows.jsonl for this file, and the rows of
//   controls/afar-first-use-malloc-direct.c and -stack.c, ran the 53-line text of this file
//   (results/malloc-dd/final/afar-first-use-malloc*.c). The later experiment rows (exp_rows.jsonl: env-*, reduction-4-trials,
//   libc-file-*, reduction-no-fence, reduction-device-release-fence-before-free, reduction-omp-flush-before-free) and the
//   harness rows of the fence and flush controls ran results/malloc-dd/final/repro.c, fence.c and flush.c as
//   `tools/campaigns/malloc_dd.py final` regenerated them: 56 lines, copy data/reports/kbody-jobs/malloc/repro-56-lines.c, sha256
//   e9cea06ba2db80e9... . It is the same program with the declaration `int i = ..., j = ..., k = ...;` split into one
//   declarator per statement (the pre-run race rule takes only the first name of a declaration list as local) and
//   `free(tmp);` on its own line. Those rows recorded the path and no source hash (experiment rows now record `src_sha256`
//   and `src_lines`), so which text a row ran is known from the path and the job, not from the row; for env-* and
//   reduction-4-trials it is not recorded whether the file was regenerated yet. The fence and flush controls differ from this
//   file by those two edits and the added fence line, so they are one change from the 56-line text, not from this file
// - other families: cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), gcc_sm80 (GCC 16.2.0) run the file correctly (rows
//   results/malloc-dd/finding_rows.jsonl, results/malloc-dd/finding_rows.jsonl); nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9)
//   fail it another way, e.g. `exit_status: 1; without mandatory: exit_status: 1`
// - gate and confirmer: 1 of 2 cells reproduce in all four environments (a-d; (c) node not recorded for every cell; rows
//   results/malloc-dd/finding_rows.jsonl, results/malloc-dd/finding_rows.jsonl)
// - legality: implementation contract (no OpenMP rule): every iteration writes only gps[cc] (cc its own index) and its own
//   malloc'd block (tmp, declared in the loop body, so private by scope, 5.2 §5.1.1), and no iteration reads another's, so
//   there is no data race and the result does not depend on the schedule. Witnesses: the rules (offload.engine.rules,
//   offload.engine.prerun.rules_witness) accept the controls (direct stores and the stack temporary) and report two things on
//   this file: i, j, k as written in every iteration (the rule takes only the first name of a declaration list as local; with
//   one declarator per statement it does not report them) and `tmp[0] = i` as a shared element (the rule does not see that
//   tmp points to a block this iteration allocated; tests/engine/test_malloc_dd.py records this report): both are limits of the
//   rule, so the rules are not a clean witness here. CCE 21.0.3 and 21.0.4 (craycc) compile and run this file correctly (rows
//   below): the Cray C front end accepts it. AFAR's front end is the compiler under test and GCC 16.2 (which also runs it
//   correctly) is no witness. The program does not check the result of malloc: a malloc that returned NULL would fault, not
//   write wrong records.
// - evidence chain (the reduction, results/malloc-dd/; the Fortran program of the student is an observation of the same
//   issue, not a finding: data/reports/kbody-observations/afar-device-array-constructor-corrupts-records.f90, `unspecified` by
//   the kernel-body model and witnessed only by AFAR's front end): (1) the student's MFC code assigns an array constructor to
//   a component, which flang lowers inside the kernel to a heap temporary: the device FIR of the Fortran reproducer (amdflang
//   -save-temps, results/student-repro/ir/orig/*-gfx942-fir.mlir; excerpt tests/data/devtemps_student_kernel.mlir) has
//   `fir.allocmem !fir.array<3xi32> {bindc_name = ".tmp.arrayctor"}` inside the omp.target region, and the device assembly
//   (results/student-repro/ir/orig/orig.x.amdgpu9.42.gfx942.img.lto.s) contains the inlined device malloc and 51 global
//   atomic operations against 1 in the element-wise kernel (5216 against 2093 lines); (2) the C port of that kernel
//   (results/student-repro/malloc/ghost3.c) fails with `malloc(12)`+memcpy+free (about 50-100 % of fresh launches), never
//   with direct stores or a stack temporary; (3) this file is its reduction (offload/engine/malloc_dd.py, tools/campaigns/malloc_dd.py:
//   greedy removal of one ingredient at a time, each candidate 8 fresh processes, kept while at least 4 fail)
// - cause (the evidence is in the next block; the model is not proven): in AFAR's OpenMP device code `free` does not release
//   the caller's earlier stores to a block before the block can be handed out again, so a block's new owner (on another
//   compute die of the MI300A, with its own L2 cache) stores its data and the old owner's dirty cache lines for the block are
//   written back afterwards: the new owner's block, and so its record, holds stale or another iteration's data. Evidence: (A)
//   in the OpenMP device image `malloc` and `free` are the LLVM libc GPU allocator (`__llvm_libc_24_0_0_git::malloc`,
//   `gpu::aligned_allocate`, a slab cache, from lib/llvm/lib/amdgcn-amd-amdhsa/libc.a: the maintainer's `llvm-nm`,
//   results/student-repro/malloc/dump.sh), not ROCm's `__ockl_dm_alloc` that the HIP image uses; `omp_alloc`/`omp_free` in
//   the kernel are the same allocator and fail alike (omp-alloc-omp-free, 10 of 10); (B) a read-back with volatile loads
//   inside the kernel (thresh3.c, 2 of 10 launches fail): in a failing launch the block is already wrong right after the
//   thread's own three stores (64 and 113 blocks in the two launches, as many records wrong), so the damage is in the
//   allocated block and not in the copy or the record array; (C) it is not a double allocation: with every thread claiming
//   its block address in a device table by atomic compare-exchange, no address was ever live in two threads and no record was
//   wrong in 10 of 10 launches (thresh4.c: the extra atomics (acquire-release compare-exchange, release store) perturb the
//   failure away, which fits a cache effect and shows nothing more); (D) a release before `free` removes it: `#pragma omp
//   flush` right after malloc 9 of 10 launches fail, after the memcpy just before free 0 of 10, both 0 of 10, none 10 of 10
//   (thresh5.c); `__scoped_atomic_thread_fence(__ATOMIC_RELEASE, ...)` before free: none 10 of 10, device scope 0 of 10,
//   system scope 0 of 10, system seq_cst 0 of 10 (thresh6.c): device scope is enough, so the scope is not the issue; the same
//   fence or flush before the free in the 56-line text of the reduction: 0 of 10 each
//   (controls/afar-first-use-malloc-fence.c, -flush.c, harness rows 10 of 10 correct, and
//   reduction-device-release-fence-before-free, reduction-omp-flush-before-free); (E) the code of the OpenMP device image
//   (AFAR 24.3.0, thresh.c, the same loop; excerpts below): the slab's bitfield operations are the two FLAT atomics of the
//   image, not the global atomics (all 12 global_atomic_and/or of the image are on `__llvm_rpc_client`, the RPC port lock).
//   The claim of a chunk, `flat_atomic_or ... offset:16 sc0` (assembly line 2488), has no `buffer_inv` after it (none within
//   400 lines). The release of a chunk, `flat_atomic_and ... offset:16` (line 2623), has no cache-control bits and no
//   `buffer_wbl2` before it in its path (the nearest earlier one, line 2341, is in malloc's guard path of another loop; the
//   next, line 2668, comes after the clear). In the IR before code generation (.precodegen.ll) the claim is `atomicrmw or ...
//   syncscope("agent") monotonic` (line 1332) and the clear `atomicrmw and ... syncscope("agent") monotonic` (line 1594); the
//   nearest fence before the clear is the agent release at line 1554, which belongs to the RPC-lock release just before it,
//   and the next fence, a release at line 1629, is after the clear: the caller's stores are not ordered before the clear. The
//   cause is consistent with the upstream source (llvm-project libc/src/__support/GPU/allocator.cpp; the maintainer's
//   reading, not checked here): commit e9350dc `Improve GPU allocator lane usage and fences (#182388)` (2026-02-19) removed
//   the release fence before `fetch_and(~(1u << bit), relaxed)` in Slab::deallocate and the acquire fence after the
//   `fetch_or(bitmask, relaxed)` claim in Slab::allocate (`the malloc/free interface already provides the needed
//   happens-before`), and GuardPtr::unlock releases only after the bit clear. AFAR's own libc source (ROCm/llvm-project
//   3ba19712e9fbf709f6c93d33394211ed4eeec8a7, the commit its clang reports) has neither fence: allocator.cpp line 316 is the
//   relaxed fetch_or and line 346 the relaxed fetch_and, with no fence beside them (checked in the fetched source,
//   results/student-repro/libc-build/src); that e9350dc is the change that removed them is the maintainer's reading.
//   - excerpts of the claim and the clear
//   (t.x.amdgpu9.42.gfx942.img.lto.s, 3873 lines; AFAR 24.3.0 `amdclang -fopenmp
//     --offload-arch=gfx942 -O2 -save-temps`; the maintainer's build, results/student-repro/malloc/cmp/omp: assembly sha256
//     66b080a8b71052a3, IR 6798d10901cbc76e; a fresh build of the same source in the harness, results/malloc-dd/isa.json:
//     assembly sha256 4900b9ec901d4a04, the same two flat atomics at the same lines and the same counts below; thresh.c
//     sha256 5327a7cee25598e6). Claim:
//         v_not_b32_e32 v7, v40
//         v_lshlrev_b32_e32 v27, v18, v7
//         v_cmp_eq_u32_e32 vcc, v28, v6
//         v_mov_b32_e32 v7, 0
//         s_and_saveexec_b64 s[0:1], vcc
//         s_cbranch_execz .LBB2_269
//       ; %bb.268:                              ;   in Loop: Header=BB2_266 Depth=3
//         v_lshrrev_b32_e32 v7, 3, v18
//         v_and_b32_e32 v12, 0x1ffffffc, v7
//         v_lshl_add_u64 v[40:41], v[8:9], 0, v[12:13]
//         flat_atomic_or v7, v[40:41], v27 offset:16 sc0
//       .LBB2_269:                              ;   in Loop: Header=BB2_266 Depth=3
//         s_or_b64 exec, exec, s[0:1]
//     Clear (free):
//         v_add_u32_e32 v12, 1, v4
//         v_cmp_ge_u32_e32 vcc, v11, v0
//         v_mov_b64_e32 v[14:15], 0
//         s_nop 0
//         v_cndmask_b32_e32 v0, v4, v12, vcc
//         v_lshrrev_b32_e32 v4, 3, v0
//         v_lshlrev_b32_e64 v0, v0, 1
//         v_and_b32_e32 v12, 0x1ffffffc, v4
//         v_lshl_add_u64 v[2:3], v[2:3], 0, v[12:13]
//         v_not_b32_e32 v0, v0
//         flat_atomic_and v[2:3], v0 offset:16
//         s_branch .LBB2_279
//       .LBB2_278:                              ;   in Loop: Header=BB2_279 Depth=3
//   - counts in this image: buffer_wbl2 38, buffer_inv 19, global_atomic 50, flat_atomic 2, s_sleep 4 (the maintainer's HIP
//     image, which uses `__ockl_dm_alloc`: buffer_wbl2 59, buffer_inv 36, global_atomic 85, s_sleep 68)
// - upstream fix test (AFAR 24.3.0's own libc, rebuilt with the two fences put back; the cure at the level of the allocator):
//   the amdgcn LLVM libc was built from ROCm/llvm-project 3ba19712e9fbf709f6c93d33394211ed4eeec8a7 with AFAR's own clang
//   (data/reports/kbody-jobs/malloc/build_libc.sh, -DLIBC_TARGET_TRIPLE=amdgcn-amd-amdhsa) in three variants, and the
//   reproducer was linked against each with `-Xoffload-linker <build>/libc/lib/libc.a` (a plain -L has no effect: the images
//   were identical). ctl: the source unmodified. rel: the release fence before the bit clear in Slab::deallocate, the patch
//   below (data/reports/kbody-jobs/malloc/libc-fence-release-only.patch). relacq: rel and an acquire fence after a successful
//   claim in Slab::allocate (data/reports/kbody-jobs/malloc/libc-fence-release-acquire.patch), which, by the maintainer's
//   reading, are the two fences e9350dc removed. Patch rel:
//       --- a/libc/src/__support/GPU/allocator.cpp  2026-11-02 17:30:19.000000000 -0800
//       +++ b/libc/src/__support/GPU/allocator.cpp  2026-11-02 17:31:49.000000000 -0800
//       @@ -342,6 +342,7 @@
//            uint32_t slot = index / BITS_IN_WORD;
//            uint32_t bit = index % BITS_IN_WORD;
//       
//       +    cpp::atomic_thread_fence(cpp::MemoryOrder::RELEASE);
//            cpp::AtomicRef(get_bitfield()[slot])
//                .fetch_and(~(1u << bit), cpp::MemoryOrder::RELAXED);
//          }
//   - validity of the build: the ctl image of thresh.c is the image linked against AFAR's stock libc.a: after replacing the
//     build-path hashes in symbol names, the assembly is the same (md5 8e6e223241ab, 3873 lines, 0 differing lines; the
//     maintainer's raw md5 792f0fb6446a on fixed paths, 3873 lines), so the rebuild reproduces the shipped allocator code;
//     the student's Fortran executables built against stock and ctl are byte-identical (sha256 f27ec8523a5a...). The rel
//     image adds `buffer_wbl2 sc1` and `s_waitcnt vmcnt(0)` before the flat_atomic_and (assembly line 2578, the clear at line
//     2624; 3876 lines); the relacq image also has a `buffer_inv` after the claim (line 2503; 3881 lines). Image facts:
//     results/malloc-dd/libc_image.json.
//   - results, fresh processes, MI300A, HSA_XNACK=1 (rows: results/malloc-dd/exp_rows.jsonl group libc,
//     results/malloc-dd/libc_fortran_rows.jsonl, run on tuolumne1028; the maintainer's own runs and scripts are copied to
//     results/malloc-dd/libcab/). C reproducer (thresh.c, 20M iterations, all allocating), two interleaved rounds of 5
//     launches per variant: stock libc 10 of 10 launches damaged (862 to 2929 bad records), ctl 10 of 10 (903 to 3172 bad
//     records), rel 0 of 10, relacq   0 of 10; the maintainer's runs: ctl 10 of 10 (1007 to 2052 bad), rel 0 of 10, relacq 0
//     of 10 (libcab/ab_rows.txt).   The 56-line text of the reduction, not this 53-line file (exp_rows libc-file-*, 10
//     launches each; see `which text ran`): ctl 10 of 10, rel 0 of 10, relacq 0 of 10. The   student's Fortran program
//     (orig.f90, `10 50 6`: 6 trials per launch; executables built by the maintainer against each   variant), 5 launches
//     each: stock 4 of 5 launches damaged (5 of 30 trials), ctl 4 of 5 (6 of 30), rel 0 of 5 (0 of 30),   relacq 0 of 5 (0 of
//     30); the maintainer's runs: stock 5 of 5 (8 of 30), ctl 5 of 5 (5 of 30), rel 0 of 5, relacq 0 of   5
//     (libcab/f_rows3.txt). The release fence before the slab bit clear alone cures both the C reproducer and the student's
//     Fortran program (flang's array-constructor temporary goes through the same device malloc and free); rel and relacq
//     behave alike, so the acquire side is not shown to matter. The whole-process wall time of the maintainer's C launches
//     was 1.6 to 1.9 s for rel and relacq against 1.7 to 3.2 s for ctl: no slowdown was visible at that granularity (not
//     measured precisely).
//   - so no source workaround is needed once a libc with the release fence ships: the fence, `omp flush` or Fortran rewriting
//     below are for the allocator as shipped.
// - mechanism (rows: results/malloc-dd/exp_rows.jsonl groups xcc, bare, patchform, sizes, run on tuolumne1011; the
//   maintainer's own runs, sources and scripts are in results/malloc-dd/libcab/ and data/reports/kbody-jobs/malloc/; the
//   write-back order itself is inferred, not traced). (1) The damage needs allocating threads on more than one XCC and grows
//   steeply with their number. xcc3.c lets only the iterations whose hardware XCC id (`s_getreg_b32 ...
//   hwreg(HW_REG_XCC_ID)`) is in a mask allocate, so every row has the same number of allocations per launch (20M) on 1, 2, 3
//   or 6 of the six XCCs (compute chiplets, each with its own L2 cache) of an MI300A; control libc, HSA_XNACK=1; launches
//   damaged (damaged records):
//       XCCs allocating            maintainer (launches per mask in brackets)                    here (6 launches per mask)
//       1  (0x1, 0x10)             0 of 14 (0 records of 280M allocations)                        0x10: 0 of 6
//       2  (0x3 0x5 0xc 0x14 0x24) 2, 3, 3, 3, 1 of 8 (146 to 704 records per 160M)             0x3: 5 of 6 (158 to 1904)
//       2  (0x30, 0x11)            0 of 6 each
//       3  (0x7 0x38 0x15 0xe)     7 of 8, 7 of 8, 8 of 8, 6 of 6 (8k to 21k records)            0x7: 6 of 6 (569 to 2589)
//       6  (0x3f)                  6 of 6 and 10 of 10 (about 1k records per launch)             6 of 6 (473 to 1666)
//       release-fence libc, 0x10 and 0x3f   0 of 4 each                                          0 of 4 each
//   The pairs 0x30 and 0x11 showed no damage, so not every pair is equally affected; one pair (0x3) damaged more launches
//   here than in the maintainer's runs (5 of 6 against 2 of 8). Also from the maintainer (not row-backed: xcc.c,
//   run_mech.sh; the output was not saved as a row file): a default launch spreads the iterations evenly over the six XCCs
//   (3.33M each) and the damage is on all of them; with `num_teams` 1 (one XCC) and 2 (two XCCs) 0 of 3 launches each
//   damaged, with 6 teams 2 of 3, with 12 or more heavily (not row-backed); HSA_CU_MASK was ignored by the OpenMP runtime
//   (all six XCCs still used) and cannot confine. This is consistent with several L2 caches that are not coherent with each
//   other for this memory; it is not a trace of the write-backs. (2) What the cure is: bare instructions before `free`
//   (thresh7.c, 20M, control libc), launches damaged, maintainer (6 launches per row) and here (4):
//       nothing                                   6 of 6    4 of 4
//       compiler barrier only                     6 of 6    4 of 4
//       `s_waitcnt vmcnt(0)` alone                6 of 6    4 of 4   (waiting for the thread's own stores is not the cure)
//       workgroup-scope release fence             6 of 6    4 of 4
//       `buffer_wbl2 sc1` alone (no wait)         0 of 6    0 of 4
//       `buffer_wbl2 sc1` and `s_waitcnt vmcnt(0)` 0 of 6    0 of 4   (what the agent-scope release emits on gfx942)
//       device-scope release fence                0 of 6    0 of 4
//   So the cure is the L2 write-back that an agent-scope release performs on gfx942. A tag test of the maintainer (xcc2.c:
//   read the previous owner's XCC tag from the chunk before writing it; libcab/xcc2_rows.txt) did not separate a previous
//   owner on the same XCC from one on another XCC, and the tag read is itself unreliable in exactly the damaged cases:
//   inconclusive, not cited as evidence either way. (3) Patch forms (thresh.c, 20M, 10 launches each, here and in the
//   maintainer's runs): ctl 10 of 10 damaged, rel (release fence before the `fetch_and`) 0 of 10, relacq (that and an
//   acquire fence after the claim) 0 of 10, rmw (the `fetch_and` with RELEASE and the claim `fetch_or` with ACQUIRE, no
//   separate fences; data/reports/kbody-jobs/malloc/libc-rmw-rmw.patch) 0 of 10 and 0 of 10, rmwrel (the `fetch_and` with
//   RELEASE only; libc-rmw-rmwrel.patch) 0 of 10 and 0 of 10. Their images link and differ as expected (maintainer's isa-<v>
//   directories: rmw has `buffer_wbl2` before the clear and `buffer_inv` after the claim, rmwrel the `buffer_wbl2` only; not
//   re-derived here). The cleanest form is RELEASE on the `fetch_and` in Slab::deallocate and ACQUIRE on the `fetch_or` in
//   Slab::allocate (rmw); rmwrel is the minimum that cures these tests; both cure, and which form to take is for the
//   maintainers. (4) Allocation sizes (sizes.c: each thread mallocs `size` bytes, stores three tags at the start, middle and
//   end, copies them into its record, frees; rounds alternate two size classes so that slabs change chunk class between
//   launches): 2048/4096 B (4M threads, 3 launches): ctl 3 of 3 damaged (8 to 264 records), rel 0 of 3, rmw 0 of 3, rmwrel 0
//   of 3, relacq 0 of 3, as in the maintainer's runs; 64/128 B (the rounds alternate the two sizes; 20M threads): ctl 3 of 3
//   (1269 to 1662), rel 0 of 3; the maintainer also found ctl 3 of 3 and rel 0 of 3 at 64 B (rounds of 32/64 B) and 256 B
//   (128/256 B), so the damage is not an effect of 16 bytes sharing a cache line. At 65536 B (500k threads) ctl itself had 0
//   of 3 damaged, so that size says nothing about the fix. The rows for 16 B and 32 B are void and not cited (for chunk sizes
//   up to 16 bytes the first, middle and last tags overlap in the same word, so every libc fails; libcab/run_b_rows.txt and
//   sizes_rows_a.txt keep them). The path for 1 MiB and more (rpc_allocate and rpc_free, no bitfield) was not exercised. (5)
//   Cost (timing.c, kernel time only, data resident, malloc(12), copy and free per iteration, n = 20M, 5 processes of 5
//   launches each; the maintainer's rows, libcab/run_b_rows.txt, medians recomputed here from them): warm launches, records
//   mapped from the host: ctl 44.5 ms, rel 35.8, relacq 35.4, rmw 36.9, rmwrel 34.8; records in device memory: ctl 39.7, rel
//   32.9, relacq 32.8, rmw 34.8, rmwrel 32.4; first launch (host-mapped records, includes the page faults): ctl 799 ms
//   against 822 to 897 for the patched variants (about 3 to 12 %, within the spread of the five processes, not resolved). No
//   slowdown was detected beyond noise; this does not show that the patch is faster. Limits: one micro-benchmark, 5
//   processes, no other workload.
// - rates (fresh processes, AFAR 24.3.0, MI300A, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; rows:
//   results/malloc-dd/rows.jsonl for the launch counts, results/malloc-dd/exp_rows.jsonl for the experiments below, harness
//   rows in results/malloc-dd/finding_rows.jsonl): this file fails 8 of 8 launches (twice) and 10 of 10 repeats of the
//   harness row. With 4 trials per process (exp_rows reduction-4-trials) the failure is in trial 1 in 8 of 8 launches (1720
//   to 8937 wrong records of 47,916,000) and in a later trial in 1 of 24 trial results (trial 3, 64 records, one wavefront):
//   the failure is mostly in the first kernel launch of a process, not only there. At HSA_XNACK=0 this file fails 1 of 8
//   launches and 1 of 10 repeats (in trial 2, 128 records), so XNACK page faults raise the rate and are not required (see the
//   build variants below). Controls: direct stores (controls/afar-first-use-malloc-direct.c) 0 of 8 launches and 0 of 10
//   repeats; a stack temporary (controls/afar-first-use-malloc-stack.c) 0 of 8 and 0 of 10; a warm-up kernel of 1000 mallocs
//   before the real kernel (results/malloc-dd/final/warm.c, not a control: it still fails) 0 of 8 launches but 2 of 10
//   repeats of the harness row (in trial 2); with 1 and 1,000,000 mallocs 5 of 8 and 2 of 8: a warm-up lowers the rate in
//   this reduction and does not remove it
// - ingredients, by removal from the student's C port (8 fresh launches each, XNACK=1, rows.jsonl): NOT needed (still 8 of
//   8): the neighbour search with its exit, the sphere lattice, collapse(3), the atomic capture (a precomputed slot does as
//   well), the other field stores, the 20-field record, mapping the marker array (omp_target_alloc for it: 8 of 8). NEEDED:
//   the malloc'd block feeding the stores (three stores from the block instead of the memcpy: 0 of 8; whether the compiler
//   then drops the block was not examined) and the record array allocated by the target construct (omp_target_alloc instead:
//   1 of 8)
// - what drives the rate (exp_rows.jsonl, thresh.c: a flat loop, each iteration with hash % 100 < share mallocs 12 bytes,
//   stores 3 ints, memcpy into its own record of a map(alloc:) calloc'd array, frees; 8 fresh launches each, XNACK=1): there
//   is no trip-count threshold: all iterations allocating, n = 12M, 16M, 16.7M, 16,777,216, 16.9M, 20M, 20,123,648 and 48M
//   all fail 8 of 8; the share of iterations that allocate lowers the rate: 25 % of 20M iterations 5 of 8, 25 % of 48M 4 of
//   8, 10 % of 48M 4 of 8 (12M mallocs packed into 12M iterations 8 of 8). The earlier "255^3 cells 0 of 8, 271^3 8 of 8"
//   came from a candidate whose checker-block marker made only half of the cells allocate; with every cell allocating the
//   reduction fails 8 of 8 at 255 and 7 of 8 at 271 (recheck-reduction-dim255, -dim271), so that result is retracted
// - first touch of the record pages (thresh2.c, n = 20M, all iterations allocate): calloc'd pages untouched 8 of 8; host
//   memset 0 8 of 8; host memset 0xff 8 of 8; one GPU write per 4 KiB page by a small kernel before the real one 0 of 8
// - build and memory mode (thresh2.c, n = 20M): default target gfx942 8 of 8 at XNACK=1 and 1 of 8 at XNACK=0; gfx942:xnack+
//   8 of 8 at XNACK=1, does not run at XNACK=0 (8 of 8 refused); gfx942:xnack- does not run at XNACK=1 (8 of 8 refused, image
//   incompatible) and fails 2 of 8 at XNACK=0: page faults amplify the failure and are not required, and a build that does
//   not replay on a fault is not a remedy
// - environment (this file, 8 launches each): LIBOMPTARGET_HEAP_SIZE=32 MiB 8 of 8, 4 GiB 8 of 8, LIBOMPTARGET_STACK_SIZE=64
//   KiB 8 of 8, nothing set 8 of 8: none changes it
// - other compilers and programming models, same loop: CCE 21.0.3 and 21.0.4 (this file, C, both memory modes) 0 of 10
//   repeats each; GCC 16.2 sm_80 0 of 10; NVHPC 25.11 and 26.9 abort with CUDA_ERROR_ILLEGAL_ADDRESS in the kernel in every
//   run, both memory modes (a different failure, not diagnosed); the loop as a HIP kernel built with amdclang++ -x hip
//   against ROCm 7.2.1 (hipthresh.hip.cpp: grid-stride loop on a 4096 x 256 grid; hipthresh2.hip.cpp: one thread per element
//   on a grid of n/256 blocks, the shape of the OpenMP kernel), 20M elements, calloc'd host array: 0 of 8 launches each at
//   HSA_XNACK=1 (at HSA_XNACK=0 neither runs: illegal memory access, host memory not reachable): ROCm's device malloc is not
//   affected in these two launch shapes; the failure is in AFAR's OpenMP offload path (the maintainer found its own
//   device-malloc initialisation kernel, omp_dm_init_kernel, in the AFAR device image: results/student-repro, no row here)
// - workarounds (for the allocator as shipped; the libc patch above removes the need): for explicit malloc/free in C: a
//   release before free (`__scoped_atomic_thread_fence(__ATOMIC_RELEASE, __MEMORY_SCOPE_DEVICE)` or `#pragma omp flush`
//   between the last store to the block and free), 0 of 10 in this file's controls; it is not available for
//   compiler-generated frees (flang frees an array-constructor temporary at the end of the statement), so for Fortran: have
//   no heap temporary in the kernel (element-wise stores, a small fixed-size private or stack array), or `-fstack-arrays`
//   (every array temporary of the program on the stack whatever its size: a program-wide cost, unsafe for large temporaries;
//   the maintainer's runs of the Fortran program, results/student-repro/variants3.txt, 0 of 4, not a harness row and not
//   row-backed). A warm-up kernel is not a workaround: it lowered the rate in this reduction and did not remove it
// - NOT shown: other AFAR releases (only 24.3.0's libc source was built and run); other GPUs (MI250X, a single XCC per GCD,
//   showed no failure; no other device was run); the patch in a libc test suite or in a performance benchmark beyond the
//   micro-benchmark above; a trace or counter of the L2 write-backs (the write-back order is inferred from the XCC
//   dose-response and the bare-instruction table); whether upstream llvm-project main and ROCm amd-staging still lack both
//   fences as of 2026-11-02 (the maintainer's check, not repeated here); the path for 1 MiB and more; why the first launch
//   of a process is the usual one, why a record array no GPU has touched is needed, why XNACK=1 raises the rate and why this
//   reduction also fails sometimes at XNACK=0 (1 of 8) while the student's program did not; NVHPC's abort
// - what an AMD engineer needs: first, the patch and its A/B: the release fence before the relaxed `fetch_and` in
//   Slab::deallocate (libc/src/__support/GPU/allocator.cpp line 346 in the commit AFAR 24.3.0 was built from; patch above),
//   which restores, by the maintainer's reading, half of what llvm/llvm-project e9350dc (2026-02-19) removed: a rebuilt libc
//   linked in with `-Xoffload-linker` takes the 56-line text of this reduction from 10 of 10 launches damaged to 0 of 10 (and
//   thresh.c, the same loop with 20M iterations, from 10 of 10 to 0 of 10), and the student's Fortran program (an
//   observation, not a finding) from 4 of 5 to 0 of 5 (5 of 5 to 0 of 5 in the maintainer's runs). Then this 53-line file
//   and the build `amdclang -fopenmp --offload-arch=gfx942 -O2 afar-device-malloc-in-kernel-corrupts-records.c` (AFAR 24.3.0,
//   therock-afar-24.3.0-multiarch-10.1.0-592954c) run as `HSA_XNACK=1 OMP_TARGET_OFFLOAD=mandatory ./a.out`, a fresh process
//   each time (it prints `trial 1: bad N ...` and `RESULT ran_on_host=0 check=fail`); the source-level A/B (the 56-line text
//   with a release fence or `omp flush` before free, 0 of 10, against 10 of 10 without); the allocator identification (libc.a
//   symbols `__llvm_libc_24_0_0_git::malloc`, `gpu::aligned_allocate`, the slab cache; the HIP image uses `__ockl_dm_alloc`
//   and is clean); the assembly and IR facts above (the claim without acquire, the clear without release; hashes); the
//   read-back result (the block is wrong right after the thread's own stores); the density and first-touch results; the
//   rates; the nodes (tuolumne1021 and tuolumne1028, MI300A, four APUs, launches pinned one per APU with
//   ROCR_VISIBLE_DEVICES)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>
#define M 439
#define N 329
#define P 329
#define B 10
#define L 3
#define NJ (N + 1 + 2 * B)
#define NK (P + 1 + 2 * B)
#define IX(i, j, k) ((((long)((i) + B)) * NJ + ((j) + B)) * NK + ((k) + B))
typedef struct { int loc[3]; int ib; } gp_t;
int main(int argc, char **argv) {
  int trials = argc > 1 ? atoi(argv[1]) : 2; long warm = argc > 2 ? atol(argv[2]) : 0L; int dev = omp_get_default_device();
  size_t tot = (size_t)(M + 1 + 2 * B) * NJ * NK; int *sf = calloc(tot, sizeof(int)); long nc = (long)(M + 1) * (N + 1) * (P + 1);
  long ng = nc;
  long nrec = nc; gp_t *gps = calloc(nrec, sizeof(gp_t));
  int *sfp = sf;
  gp_t *gpp = gps;
#pragma omp target enter data map(to : sf[0 : tot]) map(alloc : gps[0 : nrec])
  int host = 1; long tbad = 0;
#pragma omp target map(from : host)
  host = omp_is_initial_device();
  printf("cells %ld ghost %ld\n", nc, ng);
  if (warm > 0) { long wb = 0;
#pragma omp target teams distribute parallel for reduction(+ : wb)
    for (long w = 0; w < warm; w++) { int *p = (int *)malloc(3 * sizeof(int)); if (!p) { wb++; continue; }
      p[0] = (int)w; if (p[0] != (int)w) wb++; free(p); }
    printf("warm-up: bad %ld\n", wb); }
  for (int t = 1; t <= trials; t++) {
    int count = 0;
#pragma omp target teams distribute parallel for map(to : count)
    for (long cc = 0; cc < nc; cc++) {
      int i = (int)(cc / ((long)(N + 1) * (P + 1))), j = (int)((cc / (P + 1)) % (N + 1)), k = (int)(cc % (P + 1));
      {
        long li = ((long)i * (N + 1) + j) * (P + 1) + k;
        int *tmp = (int *)malloc(3 * sizeof(int)); tmp[0] = i; tmp[1] = j; tmp[2] = k;
        memcpy(gpp[li].loc, tmp, 3 * sizeof(int)); free(tmp);
        gpp[li].ib = 1;
      }
    }
#pragma omp target update from(gps[0 : nrec])
    long bad = 0, dup = 0, miss = 0; int *hits = calloc(nc, sizeof(int));
    for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++) {
      gp_t *r = &gps[((long)i * (N + 1) + j) * (P + 1) + k];
      if (r->loc[0] != i || r->loc[1] != j || r->loc[2] != k) bad++; }
    printf("trial %d: bad %ld dup %ld missing %ld\n", t, bad, dup, miss); free(hits);
    tbad += bad + dup + miss;
  }
  printf("RESULT ran_on_host=%d check=%s\n", host, tbad == 0 ? "pass" : "fail");
  return 0;
}

// site:
// title: amdclang on MI300A: free() in a kernel appears not to release the stores to the block before it can be reused, so
// + records written through malloc'd temporaries come out wrong (HSA_XNACK=1)
// summary: In a target region with tens of millions of iterations that each malloc a 12-byte block, store through it, copy it
// + into a mapped record and free it, records come out wrong (HSA_XNACK=1, MI300A; legality: implementation contract (no
// + OpenMP rule)); a device-scope release fence or omp flush before free, direct stores and a stack temporary give correct
// + records.
// control: malloc/controls/afar-first-use-malloc-direct.c one change from the finding; correct on afar
// control: malloc/controls/afar-first-use-malloc-stack.c one change from the finding; correct on afar
// control: malloc/controls/afar-first-use-malloc-fence.c one change from the 56-line text (see the header); correct on afar
// control: malloc/controls/afar-first-use-malloc-flush.c one change from the 56-line text (see the header); correct on afar
// end site
