! # Finding (GCC 16.2): libgomp for amdgcn: a target region that opens a parallel num_threads(2) region 50 times aborts ("team
!   master not responding")
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: crash
! - observed: `team master not responding; slave thread abortingteam master not responding; slave thread abortingteam master not
!   responding; slave thread abortingtea` (killed by signal 6); identical signature on 1 of 1 failing cells
! - expected: runs to completion and prints `RESULT ran_on_host=0 check=pass`
! - rule: each encounter of the parallel construct creates a team that runs the region and ends: "When a thread encounters a
!   parallel construct, a team of threads is created to execute the parallel region (see Section 10.1.1 for more information about
!   how the number of threads in the team is determined, including the evaluation of the if and num_threads clauses)." (OpenMP 5.2
!   §10.1 p.223 l.12-14); nothing limits how many parallel regions a target region may run one after another
! - same-compiler control: controls/gcc-target-repeated-parallel-num-threads-abort-delete-clause-num-threads-2-control.f90 (one
!   change from this file; correct on gcc (GCC 16.2.0); rows
!   results/reduce/gcc-target-repeated-parallel-num-threads-abort/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-target-repeated-parallel-num-threads-abort)
! - legality: legal by reading: a target region whose initial thread sets the mapped flag hf and then runs a sequential loop of 50
!   iterations, each opening a parallel num_threads(2) region over an empty loop; no shared data is written in the parallel regions.
!   The rules witness (offload.engine.prerun) accepts it, and other families' front ends compile and run it correctly (the rows)
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: i, j, hf
  hf = 1
  !$omp target map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 50, 1, -1
      !$omp parallel num_threads(2)
        do j = 1, 2
        end do
      !$omp end parallel
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', 'pass'
end program p

! site:
! title: libgomp: repeated parallel num_threads regions in a target region abort
! summary: GCC 16.2 on the MI300A aborts with "team master not responding; slave thread aborting" when a target region opens a
! + parallel num_threads(2) region 50 times in a sequential loop; without the num_threads clause the program runs.
! control: fuzz/controls/gcc-target-repeated-parallel-num-threads-abort-delete-clause-num-threads-2-control.f90 one change from the
! + finding; correct on gcc
! end site
