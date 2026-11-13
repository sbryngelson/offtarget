! # AFAR and CCE: an array private to each team, written by the threads of a nested parallel do, loses the writes
!
! (from the application corpus, PRK Fortran transpose-openmp-target, tile size 32, fails its
! own check on AFAR and every CCE; the widened catalog program omp52-w-teams-private-array-parallel).
! Compile: AFAR `amdflang -fopenmp --offload-arch=gfx942` (gfx90a on MI250X); CCE `ftn -fopenmp` after
! `module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; module unload cray-mpich`; NVHPC
! `nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate|managed`; all at -O2; run with OMP_TARGET_OFFLOAD=mandatory.
! Expected: bad= 0 dev= 1 b(1:4)= 9 7 5 3
!
! Observed (2026-10-25; MI300A at HSA_XNACK 1 and 0, MI250X at HSA_XNACK 0, A100 separate and managed):
! - AFAR 24.0.0git (drop 24.3.0): bad= 64 dev= 1 b(1:4)= 1 1 1 1 (MI300A both modes, MI250X)
! - CCE 19.0.0 and 20.0.2: bad= 64 dev= 1 b(1:4)= 1 1 1 1 (MI300A both modes, MI250X)
! - CCE 21.0.3: bad= 63 dev= 1 b(1:4)= 1 3 5 7 (MI300A both modes, MI250X)
! - NVHPC 25.11 and 26.9: bad= 0 (separate and managed memory): the other family that passes
! The values read back are not the team's: b = 1 means t(3-j) = 0.
!
! Logs: data/reports/apps/.
! Controls (data/findings/apps/controls/, same compilers and modes):
! - teams-private-array-seq.f90 (the same loops without the two parallel do directives, so the team's initial
!   thread alone writes and reads t): bad= 0 on AFAR and CCE 19/20/21.
! - teams-private-array-shared.f90 (the same nested parallel do loops, the scratch array mapped and indexed by
!   the team's iteration instead of private): bad= 0 on AFAR and CCE 19/20/21.
! - teams-private-array-write-par.f90 (only the writing loop parallel): wrong on AFAR and every CCE, as above.
! - teams-private-array-read-par.f90 (only the reading loop parallel): AFAR wrong, CCE 19/20/21 correct.
! - teams-private-array-split.f90 (`target teams private(t, j)` with a separate `distribute`): AFAR correct,
!   CCE 19/20/21 wrong as above.
! So both families lose writes to the team's copy made by the threads of the nested parallel region (they
! write copies of their own); AFAR also reads copies of its own, but only with the clause on the combined
! construct. NVHPC is correct on all six programs.
!
! Basis (OpenMP 5.2):
! - §17.2 p.340 l.1-2: "The effect of the private clause is as if it is applied only to the innermost leaf
!   construct that permits it." Here that is distribute (and teams in the split control).
! - §5.3 p.105 l.21-30: "Each task that references a privatized list item in any statement in the construct
!   receives at least one new list item if the construct has one or more associated loops ... Inside the
!   construct, all references to the original list item are replaced by references to a new list item
!   received by the task ... within the same logical iteration of the loops, the same new list item replaces
!   all references to the original list item." The initial task of each team executes the iteration jt, so
!   one t serves the whole iteration.
! - §5.1.1 p.99 l.13-16: "Rules for variables with implicitly determined data-sharing attributes are as
!   follows: ... In a parallel construct, if no default clause is present, these variables are shared." t
!   has no clause on the parallel do, so it is shared there.
! - §5.4.2 p.110 l.8-10: "The shared clause declares one or more list items to be shared by tasks generated
!   by the construct on which it appears. All references to a list item within a task refer to the storage
!   area of the original variable at the point the directive was encountered." At the parallel directive,
!   t is the team's (iteration's) new list item, so the threads write and read that storage.
! - §1.4.1 p.27 l.30-35 (memory model): "A private variable in a task region that subsequently generates an
!   inner nested parallel region is permitted to be made shared for implicit tasks in the inner parallel
!   region. ... Any other access by one task to the private variables of another task results in
!   unspecified behavior." This is the access here: the team task's private t, shared by the implicit tasks of
!   the nested parallel regions.
! - §10.2 p.230 l.12-13: "When a thread encounters a teams construct, a league of teams is created. Each team
!   is an initial team, and the initial thread in each team executes the teams region."
! Race-free: each thread of the first parallel do writes its own t(j); the loop ends with an implied barrier
! (§11 p.240 l.5-7: "an implied barrier exists at the end of the worksharing region, unless a nowait clause
! is specified") before the second parallel do reads t(3-j); b(jt+j) is written once; dev is written once,
! by the initial thread of the team with jt = 1. j is private (the parallel do's loop variable is
! predetermined private, §5.1.1; teams-level j is listed private). Legality was read against the spec; no
! compiler under test, gfortran or gcc is a legality witness.
!
! Workaround in application code: give the scratch array a team dimension and map it (the shared control), or
! keep the scratch private to the parallel loop's own iterations; the PRK transpose tile size 1 run (no
! team-private tile) is correct everywhere.
program teams_private_array_nested_parallel
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), t(0:3), i, j, jt, bad, dev
  do i = 1, n
    a(i) = i
  end do
  b = 0
  dev = -1
  !$omp target teams distribute private(t, j) map(to: a) map(from: b) map(tofrom: dev)
  do jt = 1, n, 4
    !$omp parallel do
    do j = 0, 3
      t(j) = a(jt + j)
    end do
    !$omp end parallel do
    !$omp parallel do
    do j = 0, 3
      b(jt + j) = 2*t(3 - j) + 1
    end do
    !$omp end parallel do
    if (jt == 1) dev = merge(0, 1, omp_is_initial_device())
  end do
  !$omp end target teams distribute
  bad = 0
  do i = 1, n
    if (b(i) /= 2*(2*(4*((i - 1)/4) + 1) + 3 - i) + 1) bad = bad + 1
  end do
  print '(a,i0,a,i0,a,4(1x,i0))', 'bad= ', bad, ' dev= ', dev, ' b(1:4)=', b(1:4)
end program teams_private_array_nested_parallel
! site:
! title: ftn: an array private to target teams distribute and shared by a nested parallel do loses the parallel region's writes
! control: ../vendor/checks/src/afar/control/afar-cce-teams-private-array-nested-parallel-wrong-control.f90 the same loops
! + without the two
! + parallel do directives (each team's initial thread runs them)
! end site
