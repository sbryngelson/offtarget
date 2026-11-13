! # Finding (fortran-oop): declare reduction on a derived type is rejected in target loops (Unsupported OpenMP construct)
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy, unified), cce20 (CCE 20.0.2: copy, unified), cce21 (CCE 21.0.3: copy,
!   unified), cce21_4 (CCE 21.0.4: copy, unified); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: rejected (not_implemented); OMP_TARGET_OFFLOAD=mandatory
! - observed: `Unsupported OpenMP construct Calls -- $udr_i_1OOP` for every combiner and initializer form (function, subroutine,
!   type-bound operator(+), default initialization, argmax, a parallel do inside target), every CCE release
! - expected: compiles; `r1= 2080 r2= 4160`
! - rule: 5.2 §5.5.11 p.139-140 (declare reduction on a derived type); the procedures it calls are declare target (§5.5.2 p.125
!   l.25-27)
! - other families: AFAR correct on all six (its earlier finding afar-udr-derived-type-link.f90 is a structure constructor
!   combiner); GCC 16.2 correct on all six
! - gate and confirmer: 48 cells, 48 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): unsupported (R05-unsupported) 48
! - programs (6): oop-dreduce-function, oop-dreduce-subroutine, oop-dreduce-operator, oop-dreduce-default-init,
!   oop-dreduce-argmax, oop-dreduce-nested (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type v2
    integer :: x = 0, y = 0
  end type v2
contains
  function vadd(a, b) result(c)
    !$omp declare target
    type(v2), intent(in) :: a, b
    type(v2) :: c
    c%x = a%x + b%x
    c%y = a%y + b%y
  end function vadd
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(v2) :: acc
  integer :: i
  !$omp declare reduction(vsum: v2: omp_out = vadd(omp_out, omp_in)) initializer(omp_priv = v2(0, 0))
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  acc = v2(0, 0)
  !$omp target teams distribute parallel do reduction(vsum: acc)
  do i = 1, n
    acc = vadd(acc, v2(i, 2 * i))
  end do
  r1 = acc%x
  r2 = acc%y
  ok = .true.
  ok = ok .and. (r1 == 2080)
  ok = ok .and. (r2 == 4160)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: declare reduction on a derived type cannot be used in a target region
! summary: A user-defined reduction on a derived type (declare reduction with a function, subroutine or type-bound operator
! + combiner) used on a target teams distribute parallel do is rejected by CCE 19, 20 and 21 ('Unsupported OpenMP construct'). AFAR
! + and GCC compile and run all six forms correctly.
! end site
