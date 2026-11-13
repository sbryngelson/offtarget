! # Finding (fortran-oop): mapping a derived type with a length type parameter: illegal address with separate memory
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11: separate), nvhpc269 (NVHPC 26.9: separate); -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -O2 (managed: -gpu=mem:managed)
! - failure: run_error (exit 1); OMP_TARGET_OFFLOAD=mandatory
! - observed: `cuMemcpyDtoHAsync returned error 700 (CUDA_ERROR_ILLEGAL_ADDRESS)` in separate memory, NVHPC 25.11 and 26.9;
!   managed memory correct
! - expected: `r1= 16 r2= 1496`
! - rule: 5.2 §5.8.3 p.155 l.5-7 (the new list item has the type parameters of the original)
! - same-compiler control: the same program with the type's length parameter replaced by a fixed size
!   (controls/pdt-len-unparameterized.f90, one change): correct (check=pass) on NVHPC 25.11 and 26.9, separate and managed memory
!   in the stored run and the gate's four environments a-d, (c) on another node or GPU
!   (results/oop/probe/ctl2.*.pdt-len-unparameterized.*.jsonl); a kind type parameter alone (controls/pdt-kind.f90) is correct too
!   (results/oop/main/rows.part*.jsonl, results/oop/probe/ctl2.*.pdt-kind.*.jsonl)
! - other families: AFAR (not implemented) and CCE (ftn-1853) reject the programs; GCC 16.2 aborts
! - gate and confirmer: 8 cells, 8 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 8; R22-expected-weak means the expected value has one
!   source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and no compiler
!   outside the failing family prints them on this program
! - programs (4): oop-pdt-len, oop-pdt-deferred, oop-pdt-array, oop-pdt-kindlen (offload/engine/oop_gen.py; this file is the first
!   one)
! - legality: for the nvhpc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type lv(m)
  integer, len :: m
  integer :: a(m)
  end type lv
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(lv(16)) :: x
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  do i = 1, 16
    x%a(i) = i
  end do
  !$omp target map(tofrom: x) map(from: r1)
  r1 = x%m
  do i = 1, x%m
    x%a(i) = x%a(i) * x%a(i)
  end do
  !$omp end target
  r2 = sum(x%a)
  ok = .true.
  ok = ok .and. (r1 == 16)
  ok = ok .and. (r2 == 1496)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: mapping a derived type with a length type parameter faults with separate memory
! summary: A variable of a parameterized derived type with a length type parameter, mapped tofrom, faults with an illegal address
! + on NVHPC 25.11 and 26.9 when memory is separate; managed memory works. The same program with the type's length parameter
! + replaced by a fixed size works.
! control: oop/controls/pdt-len-unparameterized.f90 the same program; the type has no length parameter (a fixed size instead)
! end site
