! # Finding (fortran-oop): amdflang: a derived type with a length type parameter in a target region is not implemented
!
! - toolchains and modes that fail: afar (AFAR: copy, unified); -O2
! - build: amdflang -fopenmp --offload-arch=gfx942 -fopenmp-version=52 -O2
! - failure: rejected (not_implemented); OMP_TARGET_OFFLOAD=mandatory
! - observed: `flang/lib/Lower/ConvertType.cpp:470: not yet implemented` for the length parameter, both modes
! - expected: compiles; `r1= 16 r2= 1496`
! - rule: 5.2 §5.8.3 p.155 l.5-7 (type parameters of mapped list items)
! - same-compiler control: the same program with the type's length parameter replaced by a fixed size
!   (controls/pdt-len-unparameterized.f90, one change): correct (check=pass) on AFAR in both modes in the stored run and the
!   gate's four environments a-d, (c) on another node or GPU (results/oop/probe/ctl2.*.pdt-len-unparameterized.*.jsonl); a kind
!   type parameter alone (controls/pdt-kind.f90) is correct too (results/oop/main/rows.part*.jsonl)
! - other families: CCE rejects them too (cce-pdt-default-mapper-rejected.f90); GCC 16.2 aborts at run time
! - gate and confirmer: 8 cells, 8 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): unsupported (R05-unsupported) 8
! - programs (4): oop-pdt-len, oop-pdt-deferred, oop-pdt-array, oop-pdt-kindlen (offload/engine/oop_gen.py; this file is the first
!   one)
! - legality: the rules accept every program; the front ends of the other families: CCE compiles none (its own rejection,
!   cce-pdt-default-mapper-rejected.f90) and NVHPC's verdict is in results/oop/main/witness.jsonl; the not-implemented message is
!   AFAR's own statement of a missing feature
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
! title: length type parameters of derived types are not implemented in offload code
! summary: AMD's flang reports 'not yet implemented' for a parameterized derived type with a length type parameter used in a
! + target region. A kind type parameter works.
! control: oop/controls/pdt-len-unparameterized.f90 the same program; the type has no length parameter (a fixed size instead)
! end site
