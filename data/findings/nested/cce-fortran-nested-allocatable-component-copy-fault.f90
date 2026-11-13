! # Finding (nested-data): CCE, copy mode: a derived type with a derived-type component that holds an allocatable array, mapped
! # by enter data, makes the kernel fail
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2); modes: copy; -O2
! - build: ftn -fopenmp -O2
! - failure: crash
! - observed: `crash: SIGABRT; without mandatory: crash: SIGABRT` (killed by signal ABRT); identical signature on 2 of 2 failing
!   cells
! - expected: compiles and prints `tot= 1628` with `check=pass`
! - rule: a structure type has a predefined default mapper that maps its elements (OpenMP 5.2 §5.8.2 p.150 l.2-4: "A
!   structure type T has a predefined default mapper that is defined as if by a declare mapper directive that specifies
!   v in a map clause with the alloc map-type"), and the map clauses a mapper introduces are subject to the mappers in
!   scope (§5.8.8 p.164 l.1: "All map clauses that are introduced by a mapper are further subject to mappers that are in
!   scope"), so the default mapper of the component's derived type maps its allocatable array too; the program
!   references nothing else
! - same-compiler control: controls/n8-ctl-fixed-array-in-component.f90 (one change from this file; correct on cce19 (CCE 19.0.0),
!   cce20 (CCE 20.0.2); rows results/nested/red/tuo9.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
!   controls/n9-ctl-allocatable-in-the-variable.f90 (one change from this file; correct on cce19 (CCE 19.0.0), cce20 (CCE 20.0.2);
!   rows results/nested/red/tuo9.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
! - other families: afar (AFAR 24.3.0), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9),
!   gcc_sm80 (GCC 16.2.0) run the file correctly in managed, unified mode (rows results/nested/red/tuo9.jsonl,
!   results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl); cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc (NVHPC 25.11),
!   nvhpc269 (NVHPC 26.9) fail it another way in copy mode, e.g. `exit_status: 1; without mandatory: exit_status: 1`
! - legality: the rules (offload.engine.rules) accept it; AFAR compiles and runs it correctly (a front end of another
!   family)
program t
  use omp_lib
  implicit none
  type :: n1
    integer, allocatable :: a(:)
  end type n1
  type :: n0
    type(n1) :: nx
  end type n0
  type(n0) :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r%nx%a(8))
  do q = 1, 8
    r%nx%a(q) = 200 + q - 1
  end do
  tot = 0
  !$omp target enter data map(to: r)
  !$omp target teams distribute parallel do reduction(+: tot)
  do q = 1, 8
    tot = tot + r%nx%a(q)
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(release: r)
  ok = tot == 1628
  print '(a,i0)', 'tot= ', tot
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t

! site:
! title: CCE: nested allocatable component faults in copy mode
! summary: CCE fails in copy mode on a derived type whose component is a derived type holding an allocatable array.
! control: nested/controls/n8-ctl-fixed-array-in-component.f90 one change from the finding; correct on cce19, cce20
! control: nested/controls/n9-ctl-allocatable-in-the-variable.f90 one change from the finding; correct on cce19, cce20
! end site
