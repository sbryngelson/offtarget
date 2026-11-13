! Minimized by compliance.fuzz_min from fuzz seed 85 (fuzz-3).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (afar) checksum=1901273453)
! observed: device checksum=0 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce19, cce21
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 48, m = 8
  type :: rec_t
    integer :: o1(n)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: ib(:)
  integer :: ic(n, m)
  integer :: i, j, p1, t1
  integer(8) :: cs
  allocate(ib(n))
  do i = 1, n
    ib(i) = mod(i * 51 + 10, 101) - 15
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 8 * j) * 55 + 11, 211) - 18
    end do
  end do
  dr%o1 = 0
  p1 = -6
  ! fuzz: kernels
  !$omp target map(tofrom: dr%o1) map(to: ic) defaultmap(firstprivate: aggregate)
    !$omp teams distribute private(t1)
    do i = n, 1, -1
      t1 = 0
      dr%o1(i) = mod((mod((ic((mod(((i * 2) + 6), n) + 1), (mod(((i * 3) + 3), m) + 1)) + t1), 7) - &
          & ior((2 + ib(i)), mod(p1, 7))), 1009)
    end do
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(dr%o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: A minimized program with defaultmap and teams distribute computes checksum 0 on the device (fuzz seed 85)
! control: ../vendor/checks/src/fuzz/control/fuzz-b2-85-cce20-control.f90 defaultmap(firstprivate: aggregate) removed
! disposition: mixed rests on reading map(tofrom: dr%o1) as an explicit attribute of the structure dr; 5.2 §5.8.1 p.148 treats a
! + reference to a structure element as a reference to the structure when implicit attributes are determined, so
! + defaultmap(firstprivate: aggregate) may apply to dr
! end site
