! Minimized by compliance.fuzz_min from fuzz seed 698 (fuzz-1).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT)
! expected: runs to completion (the host run does)
! : not reproducible on the current install (AFAR 24.3.0; reruns,
!   data/vendor/README.md: held, not reproducible); kept as a record.
! observed: device: fail crash: SIGABRT; host reference (afar/cce19) checksum=260035799
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); NVHPC is no witness: it rejects it
!   (NVFORTRAN-S-0155-Unknown PROC_BIND type); the check's other witness,
!   the AFAR flang front end, is the compiler under test and is not counted; no gfortran or gcc is
!   a legality witness.
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 100, m = 5
  integer, allocatable :: ia(:)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer :: o1(n, m)
  integer :: i, j, r1a, r1b, hf1
  integer(8) :: cs
  allocate(ia(n))
  allocate(ib(n))
  allocate(ic(n, m))
  do i = 1, n
    ia(i) = mod(i * 12 + 1, 1009) - 250
  end do
  do i = 1, n
    ib(i) = mod(i * 54 + 38, 211) - 26
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 6 * j) * 33 + 24, 1009) - 451
    end do
  end do
  o1 = 0
  r1a = -11
  r1b = 65535
  hf1 = 0
  ! fuzz: kernels
  !$omp target teams map(tofrom: hf1) reduction(max: r1a) reduction(iand: r1b)
    !$omp distribute dist_schedule(static, 2)
    do i = 1, n
      !$omp parallel do reduction(max: r1a) reduction(iand: r1b) num_threads(64) proc_bind(primary)
      do j = 1, m
        o1(i, j) = ia((mod(((j * 4) + 5), n) + 1))
        r1a = max(r1a, 0)
        r1b = iand(r1b, (ishft(iand(i, 1023), (-1)) + min(ic(i, (6 - j)), ic(i, (6 - j)))))
      end do
    end do
  !$omp end target teams
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  cs = modulo(cs * 31_8 + int(r1b, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
end program fuzz_prog
! site:
! title: amdflang at HSA_XNACK=1: a parallel region with a reduction (or atomic) nested in a distribute loop of a reducing teams
! + region aborts
! same_as: fuzz/916-afar
! end site
