! NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory
! modes: the inoutset and mutexinoutset dependence types on target nowait
! constructs are accepted silently and ignored, giving a wrong answer: a
! later target nowait with depend(in: w) runs before the first one has
! written w. NVHPC documents both types as outside its subset (below), so
! the defect is an unsupported dependence type accepted without the
! message the guide promises, not a documented feature failing.
! Spec: "For the in task-dependence-type, if the storage location of at
! least one of the list items matches the storage location of a list item
! appearing in a depend clause with an out, inout, mutexinoutset, or
! inoutset task-dependence-type on a construct from which a sibling task
! was previously generated, then the generated task will be a dependent
! task of that sibling task" (5.2 §15.9.5 p.323).
! Vendor (HPC Compilers User's Guide 25.11 and 26.9 §7.4): depend on the
! target constructs "is supported as described in 2.17.11" (2.12.3-2.12.6),
! and 2.17.11: "The dependence types in, out, and inout are supported. The
! dependence types mutexinoutset and depobj, dependence modifier
! iterator(iters), depend(source), and depend(sink:vector) are not
! supported." (inoutset is in neither list); §7: "Where ignoring such
! features is not possible, or could result in ambiguous or incorrect
! execution, the compilers emit appropriate error messages at compile- or
! run-time": no message, at compile or run time.
! Expected: "sum(b) 2080".
! Observed (2026-10-24, nvfortran 25.11-0, -O2, two runs, the same):
! "sum(b) 0" with depend(inoutset: w) and with depend(mutexinoutset: w);
! with depend(out: w): 2080 (correct).
! Found by the catalog (omp52/60-clause-depend-inoutset, omp50/52/60-
! clause-depend-mutexinoutset: confirmer R20-runtime-bug); reduced by hand.
! NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
! the same flags): still present -- the same: "sum(b) 0", both modes.
! Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
! each with its own runtime libraries (LD_LIBRARY_PATH = the release's
! compilers/lib; the first 26.9 runs had loaded 25.11's): still present
! on both releases, the same output.
! NVHPC: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! Run:   OMP_TARGET_OFFLOAD=mandatory ./a.out
program p
  implicit none
  integer :: w(64), b(64), j, sp, spin(1)
  w = 0
  b = 0
  !$omp target nowait map(tofrom: w) map(from: spin) depend(inoutset: w)
    sp = 1
    do j = 1, 20000000
      sp = mod(7*sp + j, 1000003)
    end do
    spin(1) = sp
    do j = 1, 64
      w(j) = j
    end do
  !$omp end target
  !$omp target nowait map(to: w) map(from: b) depend(in: w)
    do j = 1, 64
      b(j) = w(j)
    end do
  !$omp end target
  !$omp taskwait
  print *, 'sum(b)', sum(b), '(expected 2080)'
end program p
! site:
! title: nvfortran -mp=gpu: depend(inoutset) on target nowait accepted and ignored, wrong answer
! control: ../vendor/checks/src/nvhpc/control/nvhpc-depend-inoutset-ignored-control.f90 depend(out: w) instead of
! + depend(inoutset: w)
! end site
