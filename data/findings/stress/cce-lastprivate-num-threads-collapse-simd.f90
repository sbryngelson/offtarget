! CCE 19, 20, 21: lastprivate on a composite target teams distribute
! parallel do is wrong, and varies between runs, when the parallel leaf
! runs with num_threads(2) -- or with if(parallel: .false.) and no
! num_threads. Neither collapse nor simd is needed (fix:
! this 10-line program replaces the collapse(2)/simd/num_threads(32)
! reproducer reduced from the 14-clause stress program; the
! file keeps its name so its links stay).
! Spec: lp is assigned in every iteration, so "the value of each new list
! item from the sequentially last iteration of the associated loops ... is
! assigned to the original list item" (OpenMP 5.2 §5.4.5 p.115 l.12-16),
! and on a combined target construct the list item is also map(tofrom)
! (§17.2 p.340 l.27-30). Race-free: i is the loop's iteration variable.
! Expected: lp= 200
! Observed (Tuolumne MI300A, -O2, OMP_TARGET_OFFLOAD=mandatory, 10 runs per
! cell, 2026-10-26; data/evidence/gate_probe/logs/lastprivate_simdred.txt, programs
! in data/evidence/gate_probe/lastprivate/):
! - this program (nt2): CCE 19, 20 and 21 at HSA_XNACK 0 and 1: lp= 0, 61,
!   125 or 189, varying from run to run (200 in none of the 60 runs; this
!   file as committed, which drops nt2's unused lpar: the same, 0 of 60,
!   data/evidence/gate_probe/logs/reduce.txt lpfind);
! - if(parallel: lpar) with lpar = .false. instead of num_threads(2)
!   (ifpar): the same values on all six cells;
! - with collapse(2) (collapsent2) or simd (simdnt2) added: the same;
! - control, the same directive without num_threads and if (nont): lp= 200
!   in 60 of 60 runs on CCE 19/20/21, both modes.
! Mechanism: CCE 19/20/21 warn at compile time, on this file
! and on the if(parallel: .false.) form but not on the control:
!   ftn-7256 ftn: WARNING P, File = lp.f90, Line = <the directive>
!   An OpenMP parallel construct in a target region is limited to a single
!   thread.
! (data/evidence/gate_probe/logs/lastprivate_compile.txt). Both triggers make CCE
! run the parallel leaf with one thread; so the defect is that lastprivate
! is lost when CCE serializes the parallel leaf of a composite distribute
! parallel do. The warning says nothing about lastprivate: it is not a
! diagnostic of the wrong value, and one thread must still leave lp = 200.
! The earlier reproducer (num_threads(32) on target teams distribute
! parallel do simd collapse(2) over 16 x 8 iterations: lp= 0, 20, 64 or
! 100, correct with num_teams(1) or num_teams(3),
! data/reports/fuzz-stress-audit/r7-*.f90) is this defect; so are the
! lastprivate cells of the reproduction gate's review queue
! (data/reports/gate-queue.md: fuzz and evidence programs with
! lastprivate on distribute parallel do with num_threads(2..8) or
! if(parallel: .false.), and the 14-clause stress program clauses-omp-16).
! Another family: AFAR amdflang gives lp= 200 in 20 of 20 runs (XNACK 1 and
! 0) on the simd form (simdnt2); on this form it stops with "not yet
! implemented: lastprivate clause in constructs other than
! simd/worksharing-loop/taskloop" (a compile failure, not a value).
! NVHPC documents lastprivate on distribute as unsupported (HPC Compilers
! User's Guide 25.11 §7.4, 2.9.4), so it is no witness here.
! CCE: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm)
! Run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 (or 1) ./a.out
program p
  implicit none
  integer :: i, lp
  lp = 0
  !$omp target teams distribute parallel do lastprivate(lp) num_threads(2)
  do i = 1, 200
    lp = i
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 'lp= ', lp
end program p
! site:
! title: ftn: lastprivate on target teams distribute parallel do simd collapse(2) with num_threads gives a varying wrong value
! control: ../vendor/checks/src/cce/control/cce-lastprivate-num-threads-collapse-simd-control.f90 num_threads(32) removed
! end site
