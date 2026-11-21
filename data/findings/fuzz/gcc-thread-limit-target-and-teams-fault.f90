! # Finding (GCC 16.2): GCC for amdgcn: thread_limit on a target construct and on the teams construct nested in it faults on the GPU
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: crash
! - observed: `Memory access fault by GPU node-6 (Agent handle: 0x5a28a0) on address 0x800000000. Reason: Write access to a
!   read-only page.` (killed by signal 6); identical signature on 1 of 1 failing cells
! - expected: runs to completion and prints `RESULT ran_on_host=0 check=pass`
! - rule: both clauses are allowed and each only bounds the thread count: thread_limit applies to the target and teams directives
!   (OpenMP 5.2 §13.3 p.277), and "If a teams construct with a thread_limit clause is encountered, the thread-limit-var ICV from the
!   data environment of the initial task for each team is instead set to an implementation defined value between one and the value
!   specified in the clause." (5.2 §2.4 p.46 l.1-3); nothing makes a teams thread_limit larger than the target's non-conforming
! - same-compiler control: controls/gcc-thread-limit-target-and-teams-fault-delete-clause-thread-limit-1-control.f90 (one change
!   from this file; correct on gcc (GCC 16.2.0); rows results/reduce/gcc-thread-limit-target-and-teams-fault/rows.jsonl);
!   controls/gcc-thread-limit-target-and-teams-fault-delete-clause-thread-limit-16-control.f90 (one change from this file; correct
!   on gcc (GCC 16.2.0); rows results/reduce/gcc-thread-limit-target-and-teams-fault/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run
!   the file correctly in copy, unified mode (site rows, check case
!   site-fuzz--gcc-thread-limit-target-and-teams-fault); cce19 (CCE 19.0.0) fail it another way in copy, unified mode, e.g.
!   `ftn-1370 ftn: ERROR P, File = site-fuzz--gcc-thread-limit-target-and-teams-fault.f90, Line = 20, Column = 16`
! - legality: legal by reading: target thread_limit(1) containing only a teams distribute thread_limit(16) loop with a nested
!   parallel do over an empty body; hf is set by the iteration i = 1 only. The rules witness (offload.engine.prerun) accepts it, and
!   other families' front ends compile and run it correctly (the rows)
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: i, j, hf
  hf = 1
  !$omp target thread_limit(1) map(tofrom: hf)
    !$omp teams distribute thread_limit(16)
    do i = 1, 16
      if (i == 1) hf = merge(1, 0, omp_is_initial_device())
      !$omp parallel
      do j = 8, 1, -1
      end do
      !$omp end parallel
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', 'pass'
end program p

! site:
! title: GCC: thread_limit on target and nested teams faults on the GPU
! summary: GCC 16.2 on the MI300A aborts with a GPU memory access fault (write to a read-only page) when a target construct and the
! + teams construct nested in it both carry a thread_limit clause; either clause alone runs.
! control: fuzz/controls/gcc-thread-limit-target-and-teams-fault-delete-clause-thread-limit-1-control.f90 one change from the
! + finding; correct on gcc
! control: fuzz/controls/gcc-thread-limit-target-and-teams-fault-delete-clause-thread-limit-16-control.f90 one change from the
! + finding; correct on gcc
! end site
