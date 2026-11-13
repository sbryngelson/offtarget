! # Finding (from the data/bench/fresh draft fresh-058): nvfortran's fort2 crashes on a
!   whole-array assignment to a module allocatable in a target teams loop
!
! - source: data/bench/fresh/fresh-058.f90 (NVIDIA developer forum topic 294712, the reproducer of
!   the 2024-06-05 reply, TPR 35799). The reporter's loop runs 10000 iterations that each assign
!   all of A, a data race (every iteration writes the same elements); here the loop has one
!   iteration, so the program is race-free, and the crash is the same
! - compilers: NVHPC nvfortran 25.11 and 26.9, -mp=gpu -gpu=cc80 -O2 (separate and managed memory
!   builds)
! - expected: the program compiles and prints 7. A, an allocatable module array referenced in the
!   target region, is not a scalar, so it is treated as map(tofrom) (OpenMP 5.2 §5.8.1 p.149
!   l.4-5); Z, a scalar, is firstprivate; the single iteration assigns 7 to every element
! - actual: "nvfortran-Fatal-.../maintainers/fort2 TERMINATED by signal 11", both releases, both
!   memory-mode builds (the reporter's racy form too)
! - control (same compiler): the same assignment compiles and prints 7 when A is a fixed-size
!   module array (data/reports/fresh-drafts/d058-fixed.f90), a local allocatable (d058-local.f90),
!   in a plain target region (d058-target.f90), in target teams distribute parallel do
!   (d058-tdpd.f90), or as the element assignment A(II) = Z (d058-element.f90)
! - other families: AFAR and CCE 19/20/21 compile this program and print 7 (MI300A, HSA_XNACK 1
!   and 0; MI250X)
! - legality: legal by reading: one iteration, so no two iterations touch A; the loop construct's
!   restrictions (5.2 §11.7 p.257 l.29-34, p.258 l.1-4) and its implicit order(concurrent)
!   (§10.3 p.234 l.14-24) allow the assignment
! - evidence: results/fresh-drafts/wingtip/nv.jsonl, tuo-p4.jsonl, tioga/tioga-d.jsonl (review)
MODULE GLOBALS
   IMPLICIT NONE
   REAL :: Z
   REAL, ALLOCATABLE, DIMENSION(:)::A

END MODULE GLOBALS

MODULE RECON
   USE GLOBALS

   IMPLICIT NONE

CONTAINS

   SUBROUTINE CRASH_REPRO()

      IMPLICIT NONE
      INTEGER::II

      ALLOCATE (A(10))
      Z = 7

      !$OMP target teams loop
      DO II = 1, 1
         A = Z;
      END DO
      !$OMP end target teams loop

      PRINT *, A(1)

   END SUBROUTINE CRASH_REPRO

END MODULE RECON

PROGRAM compilerCrashTest

   USE RECON
   IMPLICIT NONE

   CALL CRASH_REPRO()

END PROGRAM compilerCrashTest
! site:
! title: nvfortran -mp=gpu: fort2 crashes (signal 11) on a whole-array assignment to a module allocatable in target teams loop
! control: ../vendor/checks/src/nvhpc/control/nvhpc-teams-loop-module-allocatable-assign-fort2-crash-control.f90 the element
! + assignment
! + A(II) = Z
! + instead of the whole-array assignment A = Z
! end site
