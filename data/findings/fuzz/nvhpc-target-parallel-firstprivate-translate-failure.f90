! # Finding (parity-fuzz-c1): NVHPC: nvfortran fails with "Compiler failed to translate OpenMP region" on firstprivate on a target
! # parallel construct that contains a worksharing loop
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: compiler failure (NVFORTRAN-F-0155, exit status 2 at compile time); the harness files it as rejected, the index as
!   ice, as the C sibling nvhpc-c-parallel-for-firstprivate-in-target.c does
! - observed: `NVFORTRAN-F-0155-Compiler failed to translate OpenMP region
!   (<tmpdir>/nvhpc-target-parallel-firstprivate-translate-failure.f90: 6)`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `suma= 2272` with `check=pass`
! - rule: the target construct's clauses include firstprivate (5.2 §13.8 p.284 l.4-6), and "The semantics of the combined constructs
!   are identical to that of explicitly specifying the first construct containing one instance of the second construct and no other
!   statements." (5.2 §17.4 p.343 l.7-8): the program is target firstprivate(k) containing a parallel region with a worksharing
!   loop, which nvfortran compiles (variants)
! - vendor: "The if, private, firstprivate, is_device_ptr, and nowait clauses are supported" on the target construct and "Combined
!   constructs are supported to the extent that the component constructs are themselves supported." (NVIDIA HPC Compilers User's
!   Guide 26.9, Using OpenMP, items 2.12.5 and 2.13; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt). The C sibling,
!   firstprivate on a parallel for in a target region, is nvhpc-c-parallel-for-firstprivate-in-target.c (the same message)
! - same-compiler control: controls/nvhpc-target-parallel-firstprivate-dropped-control.f90 (one change from this file; correct on
!   nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvc1/tuo.fp2.jsonl, results/parity/nvc1/wt.fp2.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (rows results/parity/nvc1/tuo.fp2.jsonl)
! - variants: files next to the reduction in results/parity/nvc1/red/, rows results/parity/nvc1/wt.fp2.jsonl (both releases,
!   separate and managed memory) and results/parity/nvc1/tuo.fp2.jsonl: the same loop under target firstprivate(k) with a separate
!   parallel construct (nvhpc-target-firstprivate-split-variant.f90) and as target parallel do firstprivate(k)
!   (nvhpc-target-parallel-do-firstprivate-variant.f90) compile and are correct on NVHPC. The fuzz program (seed 2207) also has a
!   critical construct in the region, which the guide documents as unsupported on GPU targets; with firstprivate(p1) removed
!   nvfortran reports that error instead (an exploration compile, not a recorded row), so the translation failure comes first
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvc1/gate_abd.fp2.jsonl, results/parity/nvc1/gate_abd.fp2.m2.jsonl, results/parity/nvc1/gate_c.fp2.jsonl,
!   results/parity/nvc1/gate_c.fp2.m2.jsonl, results/parity/nvc1/wt.fp2.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127709.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127721.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210952.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210965.jsonl)
! - programs (1): par-c1-nvhpc-nvhpc269:2207
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its control and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvc1/prerun.fp2.txt); AFAR 24.3.0 and CCE
!   19/20/21/21.0.4
!   compile and run it correctly with HSA_XNACK 0 and 1 (results/parity/nvc1/tuo.fp2.jsonl). NVHPC is the compiler under test and is
!   not counted as a witness
program p
  implicit none
  integer :: a(64), i, k
  a = 0
  k = 3
  !$omp target parallel map(tofrom: a) firstprivate(k)
    !$omp do
    do i = 1, 64
      a(i) = i + k
    end do
    !$omp end do nowait
  !$omp end target parallel
  print '(a,i0)', 'suma= ', sum(a)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 2080 + 64 * 3)
end program p

! site:
! title: firstprivate on target parallel with a do loop: translation failure
! summary: nvfortran -mp=gpu appears to behave incorrectly on a target parallel construct with firstprivate that contains a
! + worksharing loop: the compile stops with "Compiler failed to translate OpenMP region". Without firstprivate, or with a separate
! + parallel construct, it compiles and runs correctly.
! control: fuzz/controls/nvhpc-target-parallel-firstprivate-dropped-control.f90 one change from the finding; correct on nvhpc,
! + nvhpc269
! end site
