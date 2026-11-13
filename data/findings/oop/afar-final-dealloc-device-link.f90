! # Finding (fortran-oop): amdflang: DEALLOCATE of an allocatable finalizable object in device code fails at the device link
!
! - toolchains and modes that fail: afar (AFAR: copy, unified); -O2
! - build: amdflang -fopenmp --offload-arch=gfx942 -fopenmp-version=52 -O2
! - failure: rejected (link_undefined_symbol, the program's own object); OMP_TARGET_OFFLOAD=mandatory
! - observed: `ld.lld: error: undefined symbol: flang_rt_verbose_abort(char const*, ...)` at the device link, both modes: the
!   device code of the DEALLOCATE (with its finalization) calls a flang runtime routine that has no device version
! - expected: compiles; `r1= 64 r2= 2144`
! - rule: Fortran 2018 7.5.6.3 para 2 (DEALLOCATE finalizes the object); the final subroutine is declare target (5.2 §1.2.6 p.19)
! - same-compiler control: a non-allocatable local of the same type (controls/final-local.f90, the family program
!   oop-assignfinal-final-local): correct in both modes (results/oop/main/rows.part*.jsonl,
!   results/oop/probe/ctl2.*.final-local.*.jsonl)
! - other families: CCE 19/20 stop the device thread at the DEALLOCATE and CCE 21 aborts (cce-final-dealloc-device-abort.f90); GCC
!   16.2 correct. The confirmer's signature also matches afar-udr-derived-type-link.f90 (the same undefined symbol, from a declare
!   reduction with a structure-constructor combiner); the triggers differ, so this is a finding of its own
! - gate and confirmer: 2 cells, 2 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): compiler_bug (R10b-own-link-or-hang) 2
! - programs (1): oop-assignfinal-final-dealloc (offload/engine/oop_gen.py; this file is the first one)
! - legality: the rules and the front ends of the other families (AFAR's own front end is not its witness): CCE compiles it (its
!   failure is at run time) and NVHPC's verdict is no verdict (an unsupported runtime routine, results/oop/main/witness.jsonl);
!   tools/campaigns/oop.py legality: legal for AFAR
module oop_m
  implicit none
  integer, parameter :: n = 64
  type ft
    integer :: v = 0
  contains
    final :: ft_fin
  end type ft
  integer :: fin_count = 0
  !$omp declare target to(fin_count)
contains
  subroutine ft_fin(o)
    !$omp declare target
    type(ft), intent(inout) :: o
    !$omp atomic update
    fin_count = fin_count + 1
  end subroutine ft_fin
  subroutine alloc_work(k, r)
    !$omp declare target
    integer, intent(in) :: k
    integer, intent(out) :: r
    type(ft), allocatable :: o
    allocate(o)
    o%v = k
    r = o%v + 1
    deallocate(o)
  end subroutine alloc_work
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  integer :: res(n), i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  fin_count = 0
  !$omp target update to(fin_count)
  !$omp target teams distribute parallel do map(tofrom: res)
  do i = 1, n
    call alloc_work(i, res(i))
  end do
  !$omp target update from(fin_count)
  r1 = fin_count
  r2 = sum(res)
  ok = .true.
  ok = ok .and. (r1 == 64)
  ok = ok .and. (r2 == 2144)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: deallocating a finalizable object in device code fails at the link
! summary: A declare target subroutine allocates and deallocates a local allocatable object of a type with a final subroutine.
! + AMD's flang fails at the device link: flang_rt_verbose_abort is undefined. The same type as a non-allocatable local is finalized
! + correctly on the device.
! control: oop/controls/final-local.f90 a non-allocatable local of the same finalizable type (no DEALLOCATE)
! end site
