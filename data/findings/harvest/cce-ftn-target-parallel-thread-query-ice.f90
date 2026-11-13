! # Finding: CCE ftn ICE "Could not find call"
! # (v_acc_dataplacement.c) when a target parallel region assigns the result
! # of omp_get_num_threads() or omp_get_thread_num()
!
! - compilers: CCE ftn 19.0.0, 20.0.2, 21.0.3, -O2: this file on MI300A
!   gfx942 (HSA_XNACK 0 and 1); its variants on MI250X gfx90a (19.0.0,
!   21.0.3); the upstream test on gfx942 (both modes) and gfx90a (gate
!   confirmed)
! - expected: compiles; prints x= <the team's size> (at least 1)
! - actual: ftn: INTERNAL COMPILER ERROR: "Could not find call"
!   (/workspace/crayftn/pdgcs/v_acc_dataplacement.c, line 4289 in 19.0.0,
!   4343 in 20.0.2, 4378 in 21.0.3) (results/harvest/probe/f6.jsonl,
!   findings_gfx942.jsonl)
! - rule: a legal program (OpenMP 5.2 §10.1 parallel, §18.2.2
!   omp_get_num_threads, §18.2.4 omp_get_thread_num; both routines are
!   among the five CCE documents as supported in offload regions:
!   intro_openmp, data/index/claims/hpe-cce-21.0.3-intro_openmp.txt). An ICE
!   is a compiler bug.
! - conditions (each a one-change variant, CCE 19.0.0 and 21.0.3): the same
!   ICE with x = omp_get_thread_num(); with the result assigned to a private
!   n, then x = n; with `target` and a nested `parallel` instead of the
!   combined construct; with x an array element; with map(tofrom: x); with
!   `use omp_lib, only: ...`; in a main program or a subroutine, with or
!   without SAVE. No ICE: `x = 7` (no call); a call in an IF condition only
!   (`if (omp_get_thread_num() == 0) then` ..., as in
!   cce19-target-parallel-guarded-loop.f90); `target teams` with
!   x = omp_get_num_teams() (x= 220).
! - other families: AFAR amdflang compiles and runs it (x= 256, gfx942 at
!   HSA_XNACK 0 and 1; parallel = T on the upstream test); NVHPC nvfortran
!   25.11 and 26.9 compile and run it (x= 13824, A100, separate and
!   managed).
! - upstream: llvm-project offload/test/offloading/fortran/
!   basic-target-parallel-region.f90 (CCE ICE on every CCE cell, gate
!   confirmed on gfx90a); AOMP test/smoke/flang-313307-simple-spmd hits the
!   same ICE.
! - legality: offload.engine.prerun.check accepts it (the rules with the race
!   rule, and the AFAR flang front end); only thread 0 writes x.
! CCE:  ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>;
!       module unload cray-mpich)
! Run:  OMP_TARGET_OFFLOAD=mandatory ./a.out
program tp_guarded
   use omp_lib
   implicit none
   integer :: x, on_host
   x = -1
   on_host = 1
   !$omp target map(from: on_host)
   if (omp_is_initial_device()) then
     on_host = 1
   else
     on_host = 0
   end if
   !$omp end target
   !$omp target parallel map(from: x)
   if (omp_get_thread_num() == 0) x = omp_get_num_threads()
   !$omp end target parallel
   print '(a,i0)', 'x= ', x
   if (x >= 1) then
     print '(a,i0,a)', 'RESULT ran_on_host=', on_host, ' check=pass'
   else
     print '(a,i0,a)', 'RESULT ran_on_host=', on_host, ' check=fail'
   end if
end program tp_guarded
! site:
! title: ftn: internal compiler error ("Could not find call") when a target parallel region assigns omp_get_num_threads() or
! + omp_get_thread_num()
! end site
