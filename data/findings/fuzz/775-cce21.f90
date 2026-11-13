! Minimized by compliance.fuzz_min from fuzz seed 775 (fuzz-1).
! toolchain: cce21 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (afar/cce19) checksum=255)
! observed: device checksum=4 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
program fuzz_prog
  use omp_lib, only: omp_get_team_num, omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 2
  integer :: i, j, r1a
  integer(8) :: cs
  r1a = 4
  ! fuzz: kernels
  !$omp target map(tofrom: r1a) defaultmap(tofrom: scalar)
    if (omp_get_team_num() == 0) then
      do i = n, 1, -1
        r1a = ior(r1a, i)
      end do
    end if
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn: with a defaultmap clause on target, an explicitly mapped map(tofrom) scalar is not copied back, and with
! + defaultmap(tofrom) an array in map(alloc) or map(to) is copied back
! same_as: cce21-defaultmap-aggregate-flag
! end site
