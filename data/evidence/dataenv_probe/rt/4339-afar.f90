! Minimized by compliance.fuzz_min from fuzz seed 4339 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT | memory access fault)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (cce19) checksum=111811640
! Legal OpenMP 5.2: passes offload.engine.rules, gfortran -std=f2008 and AFAR flang's frontend.
!@file fuzz_dmod.f90
module fuzz_dmod
  implicit none
  integer, parameter :: nm = 128
  type :: gp_t
  end type gp_t
  type :: mt_t
  end type mt_t
  type(gp_t) :: gs
  !$omp declare target to(gs)
end module fuzz_dmod
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_get_team_num, omp_is_initial_device
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 128, m = 8
  type :: rec_t
    integer :: s
  end type rec_t
  type :: el_t
    integer :: u
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  type(mt_t) :: ms
  integer, allocatable :: ia(:)
  integer :: ic(n, m)
  integer, pointer :: o1(:)
  integer :: i, j, r1a, hf1
  integer(8) :: cs
  allocate(ia(n))
  allocate(o1(n))
  do i = 1, n
    ia(i) = mod(i * 27 + 29, 1009) - 401
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 9 * j) * 34 + 30, 211) - 49
    end do
  end do
  do i = 1, n
    ds(i)%u = mod(i * 26 + 31, 97) - 21
  end do
  dr%s = 12
  o1 = 0
  r1a = 1
  hf1 = 0
  !$omp target update to(gs)
  ! fuzz: kernels
  call kp1(ia, ic, o1, dr, ds)
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
contains
  subroutine kp1(ia, ic, o1, dr, ds)
    integer, allocatable, intent(inout) :: ia(:)
    integer, intent(in) :: ic(n, m)
    integer, intent(inout) :: o1(:)
    type(rec_t), intent(inout) :: dr
    type(el_t), intent(inout) :: ds(:)
    !$omp target map(close, tofrom: ia) map(tofrom: dr%s, o1, hf1, r1a)
      if (omp_get_team_num() == 0) then
        do i = 1, n
          o1(i) = mod(ds(i)%u, 1009)
        end do
      end if
    !$omp end target
  end subroutine kp1
end program fuzz_prog
