! # Finding (fortran-oop): map(mapper(deep), tofrom: x) with a declare mapper: rejected (mapper(mapid) is not supported)
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11: managed, separate), nvhpc269 (NVHPC 26.9: managed, separate); -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -O2 (managed: -gpu=mem:managed)
! - failure: rejected (not_implemented); OMP_TARGET_OFFLOAD=mandatory
! - observed: `NVFORTRAN-W-0287-Unrecognized OpenMP directive - declare` for the declare mapper directive, then the map clause
!   naming the mapper does not compile, NVHPC 25.11 and 26.9, separate and managed memory. The default-mapper programs
!   (oop-mapper-default and four others) get the same warning and then run with the predefined default mapper, which in those
!   programs has the same effect: not counted here (their separate-memory failures are
!   nvhpc-copy-alloc-component-illegal-address.f90's)
! - expected: compiles; `r1= 133120`
! - rule: 5.2 §5.8.8 p.162-164 (declare mapper) and §5.8.2 (the mapper modifier); NVHPC documents the gap: the NVIDIA HPC
!   Compilers User's Guide §7.4 "OpenMP Subset" (the OpenMP 5.0 features the compilers support) lists for 2.19.7 that
!   mapper(mapid) is not supported, and does not list declare mapper
! - other families: AFAR and CCE correct; GCC rejects it (gcc/gcc-declare-mapper-rejected.f90)
! - gate and confirmer: 4 cells, 4 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): unsupported (R05-unsupported) 4
! - programs (1): oop-mapper-named (offload/engine/oop_gen.py; this file is the first one)
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
  !$omp declare mapper(deep: vec :: v) map(tofrom: v, v%a(1:v%n))
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
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
  !$omp target teams distribute parallel do map(mapper(deep), tofrom: x)
  do i = 1, n
    x%a(i) = x%a(i) * x%n
  end do
  r1 = sum(x%a)
  ok = .true.
  ok = ok .and. (r1 == 133120)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: a named declare mapper (map(mapper(id), ...)) is not supported
! summary: A map clause with a mapper modifier naming a declare mapper does not compile with NVHPC 25.11 and 26.9; the declare
! + mapper directive itself is reported as unrecognized. NVHPC's user guide lists mapper(mapid) as not supported. AFAR and CCE apply
! + the mapper correctly.
! end site
