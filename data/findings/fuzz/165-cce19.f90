! Minimized by compliance.fuzz_min from fuzz seed 165 (fuzz-1).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (ice: INTERNAL COMPILER ERROR: "unhandled operator)
! expected: compiles
! observed: internal compiler error: ice: INTERNAL COMPILER ERROR:  "unhandled operator
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: afar, cce20, cce21
module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = mod(max((x + y), x), 97)
  end function g1
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 16, m = 2
  integer :: o1(n)
  integer :: i, j, lp1, t1
  logical :: lpar
  integer(8) :: cs
  o1 = 0
  lp1 = 0
  lpar = .true.
  ! fuzz: kernels
    !$omp target depend(out: o1)
      !$omp parallel do lastprivate(conditional: lp1) private(t1)
      do i = n, 1, -1
        t1 = 0
        if (mod(i, 2) == 1) lp1 = i
      end do
    !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn: internal compiler error for lastprivate(conditional:) on a parallel loop in a target region
! control: ../vendor/checks/src/fuzz/control/fuzz-165-cce19-control.f90 the same parallel do on the host (the target directive
! + removed)
! same_as: fuzz/958-cce20
! end site
