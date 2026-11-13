! Minimized by compliance.fuzz_min from fuzz seed 2334 (fuzz-1).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703,
!   version <v>))
! expected: compiles
! observed: internal compiler error: ice: INTERNAL COMPILER ERROR:  "Couldn't find an atomic update statement"
!   (/workspace/crayftn/pdgcs/v_mt_translate_atomic.c, line 1703, version cc4d36e4ff3377d4
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce20, cce21
module fuzz_mod
  implicit none
contains
  integer function g1(x)
    !$omp declare target
    integer, intent(in) :: x
    g1 = mod(mod(merge(1, x, 1 > x), 13), 97)
  end function g1
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 100, m = 5
  integer :: i, j, r1b
  integer(8) :: cs
  r1b = -1
  ! fuzz: kernels
  !$omp target
    !$omp do
    do i = 1, n
      !$omp atomic
      r1b = r1b * merge((-1), 1, mod(11, 13) == 0)
    end do
    !$omp end do
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1b, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn: internal compiler error "Couldn't find an atomic update statement" for an atomic update whose factor folds to a
! + constant
! control: ../vendor/checks/src/fuzz/control/fuzz-2334-cce19-control.f90 the factor depends on i: merge(-1, 1, mod(i, 13) == 0)
! + (seven sign
! + changes, r1b = 1)
! end site
! spec (requirement): an atomic update statement of the form x = x operator expr, where operator is one of the listed operators
!   (including *) and expr is any scalar expression, is a legal update-atomic structured block; a constant-valued expr is no
!   exception.
! "x   =   x operator expr" (5.2 §4.3.1.3 p.81 l.12)
! "expr is a scalar expression." (5.2 §4.3.1.3 p.79 l.23)
! spec (this program): !$omp atomic with r1b = r1b * merge((-1), 1, mod(11, 13) == 0) is an x = x operator expr update whose
!   scalar factor folds to the constant 1; CCE 19, 20 and 21 stop with an internal compiler error (Couldn't find an atomic update
!   statement), while the same statement with a factor that depends on i compiles.
