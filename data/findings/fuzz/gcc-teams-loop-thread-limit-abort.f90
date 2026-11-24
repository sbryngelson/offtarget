! # Finding (leads): GCC 16.2 aborts at run time on a Fortran OpenMP program with a teams construct, a loop construct and a
!   thread_limit clause
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: crash
! - observed: `Memory access fault by GPU node-4 (Agent handle: 0x5a5910) on address 0x800000000. Reason: Write access to a
!   read-only page.` (killed by signal 6); identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 0` with `check=pass`
! - rule: a conforming program runs to completion: "When a thread encounters a teams construct, a league of teams is created."
!   (OpenMP 5.2 §10.2 p.230 l.12); "A loop construct specifies that the logical iterations of the associated loops may execute
!   concurrently and permits the encountering threads to execute the loop accordingly." (OpenMP 5.2 §11.7 p.257 l.8-9); "As
!   described in Section 2.4, some constructs limit the number of threads that may participate in a contention group initiated by
!   each team by setting the value of the thread-limit-var ICV for the initial task to an implementation-defined value greater than
!   zero." (OpenMP 5.2 §13.3 p.277 l.17-19)
! - same-compiler control: controls/lead-def1-16148-gcc-delete-clause-thread-limit-1-control.f90 (one change from this file; correct
!   on gcc (GCC 16.2.0); rows results/leads/reduce/lead-def1-16148-gcc/rows.jsonl);
!   controls/lead-def1-16148-gcc-delete-clause-thread-limit-64-control.f90 (one change from this file; correct on gcc (GCC 16.2.0);
!   rows results/leads/reduce/lead-def1-16148-gcc/rows.jsonl); controls/lead-def1-16148-gcc-unwrap-loop-control.f90 (one change from
!   this file; correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-def1-16148-gcc/rows.jsonl);
!   controls/lead-def1-16148-gcc-unwrap-teams-control.f90 (one change from this file; correct on gcc (GCC 16.2.0); rows
!   results/leads/reduce/lead-def1-16148-gcc/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (site rows, check case site-fuzz--gcc-teams-loop-thread-limit-abort); cce19 (CCE 19.0.0) fail it another way,
!   e.g. `ftn-1370 ftn: ERROR FUZZ_PROG, File = site-fuzz--gcc-teams-loop-thread-limit-abort.f90, Line = 39, Column = 16`
! - programs (1): def1:16148
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce20, cce21 run it correctly in the
!   confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 100, m = 8
  integer(kind=1), allocatable :: o1(:)
  complex(kind=4) :: o2(n, m)
  integer :: i, j, hf2
  integer(8) :: cs
  allocate(o1(n))
  o1 = 0
  o2 = 0
  hf2 = 0
  ! fuzz: kernels
  !$omp target thread_limit(1)
    !$omp teams thread_limit(64)
      !$omp loop
      do i = 1, n
      end do
    !$omp end teams
  !$omp end target
  !$omp target map(tofrom: hf2) defaultmap(default: all)
    !$omp teams
      !$omp distribute
      do i = n, 1, -1
        if (i == n) hf2 = merge(1, 0, omp_is_initial_device())
      end do
      !$omp end distribute
    !$omp end teams
  !$omp end target
  !$omp target exit data map(from: o1, o2)
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(real(o2(i, j)) * 64, 8), 2147483629_8)
      cs = modulo(cs * 31_8 + int(aimag(o2(i, j)) * 64, 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf2, 0), ' check=', merge('pass', 'fail', cs == 0_8)
end program fuzz_prog

! site:
! title: GCC: abort with teams, loop and thread_limit
! summary: GCC 16.2 aborts at run time on a Fortran OpenMP program with a teams construct, a loop construct and a thread_limit
! + clause.
! control: fuzz/controls/lead-def1-16148-gcc-delete-clause-thread-limit-1-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-def1-16148-gcc-delete-clause-thread-limit-64-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-def1-16148-gcc-unwrap-loop-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-def1-16148-gcc-unwrap-teams-control.f90 one change from the finding; correct on gcc
! end site
