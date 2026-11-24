! # Finding (leads): CCE 19 refuses a Fortran OpenMP program with a parallel loop construct, an if clause, a default clause and a
!   loop construct
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes:
!   unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: rejected
! - observed: `ftn-1510 ftn: ERROR FUZZ_PROG, File = site-fuzz--cce19-parallel-loop-if-default-rejected.f90, Line = 74, Column =
!   38`; identical signature on 8 of 8 failing cells
! - expected: compiles and prints `checksum= 0` with `check=pass`
! - rule: a conforming program compiles and links: "When a thread encounters a parallel construct, a team of threads is created to
!   execute the parallel region (see Section 10.1.1 for more information about how the number of threads in the team is determined,
!   including the evaluation of the if and num_threads clauses)." (OpenMP 5.2 §10.1 p.223 l.12-14); "A loop construct specifies that
!   the logical iterations of the associated loops may execute concurrently and permits the encountering threads to execute the loop
!   accordingly." (OpenMP 5.2 §11.7 p.257 l.8-9); "If no directive-name-modifier is specified then the effect is as if a
!   directive-name-modifier was specified with the directive-name of the directive on which the clause appears." (OpenMP 5.2 §3.4
!   p.72 l.11-12); "The default clause determines the implicit data-sharing attribute of certain variables that are referenced in
!   the construct, in accordance with the rules given in Section 5.1.1." (OpenMP 5.2 §5.4.1 p.109 l.8-9); "A loop construct
!   specifies that the logical iterations of the associated loops may execute concurrently and permits the encountering threads to
!   execute the loop accordingly." (OpenMP 5.2 §11.7 p.257 l.8-9)
! - same-compiler control: controls/lead-g1x0-o3-1021-cce19-delete-clause-default-none-control.f90 (one change from this file;
!   correct on cce19 (CCE 19.0.0); rows results/leads/reduce/lead-g1x0-o3-1021-cce19/rows.jsonl);
!   controls/lead-g1x0-o3-1021-cce19-delete-clause-if-parallel-lpar-control.f90 (one change from this file; correct on cce19 (CCE
!   19.0.0); rows results/leads/reduce/lead-g1x0-o3-1021-cce19/rows.jsonl);
!   controls/lead-g1x0-o3-1021-cce19-shorten-parallel-loop-to-parallel-control.f90 (one change from this file; correct on cce19 (CCE
!   19.0.0); rows results/leads/reduce/lead-g1x0-o3-1021-cce19/rows.jsonl);
!   controls/lead-g1x0-o3-1021-cce19-unwrap-parallel-loop-control.f90 (one change from this file; correct on cce19 (CCE 19.0.0);
!   rows results/leads/reduce/lead-g1x0-o3-1021-cce19/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), gcc (GCC 16.2.0) run the file correctly (site rows, check case
!   site-fuzz--cce19-parallel-loop-if-default-rejected)
! - programs (1): g1x0-o3:1021
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); the legality verdict is computed
!   (tools/review/review.py mechanical)
! - releases: CCE 19.0.0, 20.0.2, 21.0.3 and 21.0.4 fail it the same way
module fuzz_smod
  implicit none
  interface
    module integer function gs1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function gs1
  end interface
end module fuzz_smod
!@file fuzz_ssub.f90
submodule (fuzz_smod) fuzz_ssub
  implicit none
contains
  module integer function gs1(x)
    !$omp declare target
    integer, intent(in) :: x
    gs1 = 0
  end function gs1
end submodule fuzz_ssub
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_smod, only: gs1
  implicit none
  integer, parameter :: n = 32, m = 8
  type :: nd_t
  end type nd_t
  type :: rec_t
    integer :: s = (-11)
    type(nd_t) :: nd
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer :: i, j, hf1
  logical :: lpar
  integer(8) :: cs
  hf1 = 0
  lpar = .false.
  ! fuzz: kernels
  !$omp target map(tofrom: hf1)
    hf1 = merge(1, 0, omp_is_initial_device())
    !$omp parallel loop if(parallel: lpar) default(none)
    do i = 1, n, 2
    end do
  !$omp end target
  ! fuzz: checksum
  cs = 0
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', 'pass'
end program fuzz_prog

! site:
! title: CCE: rejected with parallel loop, if and default
! summary: CCE 19 refuses a Fortran OpenMP program with a parallel loop construct, an if clause, a default clause and a loop
! + construct.
! control: fuzz/controls/lead-g1x0-o3-1021-cce19-delete-clause-default-none-control.f90 one change from the finding; correct on
! + cce19
! control: fuzz/controls/lead-g1x0-o3-1021-cce19-delete-clause-if-parallel-lpar-control.f90 one change from the finding; correct on
! + cce19
! control: fuzz/controls/lead-g1x0-o3-1021-cce19-shorten-parallel-loop-to-parallel-control.f90 one change from the finding; correct
! + on cce19
! control: fuzz/controls/lead-g1x0-o3-1021-cce19-unwrap-parallel-loop-control.f90 one change from the finding; correct on cce19
! end site
