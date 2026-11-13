! # Finding (fortran-oop): map(tofrom: x) of a structure with an allocatable component: illegal address with separate memory
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11: separate), nvhpc269 (NVHPC 26.9: separate); -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -O2 (managed: -gpu=mem:managed)
! - failure: run_error (exit 1); OMP_TARGET_OFFLOAD=mandatory
! - observed: `Accelerator Fatal Error: call to cuMemcpyDtoHAsync returned error 700 (CUDA_ERROR_ILLEGAL_ADDRESS)` in separate
!   memory on NVHPC 25.11 and 26.9, whenever the allocatable component is mapped only through the structure (map(tofrom: x),
!   target enter data map(to: x), an array of such structures, an allocatable scalar component, two levels, an extended type's
!   allocatable parent component); managed memory correct
! - expected: `r1= 10336 r2= 256`
! - rule: the predefined default mapper maps each structure element, an allocatable component's data included (5.2 §5.8.2 p.150
!   l.2-4; §5.8.3 p.151 l.29-37; added in 5.0, 6.0 §B.5 p.909 l.35-37)
! - same-compiler control: the same program with the component listed, map(tofrom: x, x%a)
!   (controls/alloccomp-whole-explicit-component.f90, one change): correct (check=pass) on NVHPC 25.11 and 26.9, separate and
!   managed memory, in the stored run and the gate's four environments a-d, (c) on another GPU of the host
!   (results/oop/probe/ctl2.*.alloccomp-whole-explicit-component.wt-*.jsonl)
! - other families: AFAR, CCE 19/20/21 and GCC 16.2 correct on all nine
! - gate and confirmer: 18 cells, 18 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 18; R22-expected-weak means the expected value has
!   one source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and AFAR, CCE
!   19.0.0, CCE 20.0.2, CCE 21.0.3, CCE 21.0.4, GCC 16.2 (gfx90a), GCC 16.2 (sm_80) print them on this program
! - programs (9): oop-alloccomp-whole, oop-alloccomp-array, oop-alloccomp-enterexit, oop-alloccomp-scalar, oop-alloccomp-twolevel,
!   oop-alloccomp-update, oop-extends-alloc-parent, oop-elemsec-alloc-chain, oop-section-update (offload/engine/oop_gen.py;
!   this file
!   is the first one)
! - legality: for the nvhpc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and a CCE compile (tools/campaigns/oop.py legality,
!   results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type vec
    integer :: n = 0
    integer, allocatable :: a(:)
  end type vec
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(vec) :: x
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(x%a(n))
  x%n = n
  do i = 1, n
    x%a(i) = i
  end do
  !$omp target teams distribute parallel do map(tofrom: x)
  do i = 1, n
    x%a(i) = 3 * x%a(i) + x%n
  end do
  r1 = sum(x%a)
  r2 = x%a(n)
  ok = .true.
  ok = ok .and. (r1 == 10336)
  ok = ok .and. (r2 == 256)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: the allocatable component of a mapped structure is not mapped with separate memory
! summary: A structure with an allocatable array component mapped by map(tofrom: x) should carry the component's data to the
! + device (the predefined default mapper maps each component). NVHPC 25.11 and 26.9 fault with an illegal address when memory is
! + separate; with the component listed, map(tofrom: x, x%a), the program works, and managed memory works. AFAR, CCE and GCC are
! + correct.
! control: oop/controls/alloccomp-whole-explicit-component.f90 the same program with the component listed in the map clause
! end site
