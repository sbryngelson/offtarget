! Minimized by compliance.fuzz_min from fuzz seed 1978 (fuzz-1).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce20/cce21) checksum=1879642524)
! observed: device checksum=0 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
program fuzz_prog
  implicit none
  integer, parameter :: n = 24, m = 5
  integer :: o1(n)
  integer :: i, j, jj, acc1
  integer(8) :: cs
  o1 = 0
  ! fuzz: kernels
  !$omp target map(always, from: o1) defaultmap(firstprivate: aggregate) private(acc1, jj)
  do i = n, 1, -1
    acc1 = 0
    o1(i) = i
  end do
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! spec (requirement): explicit data-environment attribute clauses on a target construct determine the attributes of the
!   variables they name, and the implicit rules, including defaultmap, apply only to the variables that no explicit clause names,
!   so map(always, from: o1) copies the device array back whatever defaultmap(firstprivate: aggregate) says.
! "When specified, explicit data-environment attribute clauses on target directives determine the attributes for variables
!   referenced in a target construct." (5.2 §5.8.1 p.148 l.2-3)
! "If a defaultmap clause is present for the category of the variable and specifies an implicit behavior other than default, the
!   data-mapping or data-sharing attribute is determined by that clause." (5.2 §5.8.1 p.148 l.18-20)
! spec (this program): o1 is mapped explicitly with map(always, from: o1) and defaultmap(firstprivate: aggregate) must not
!   change that; CCE 19 returns checksum 0 instead of the host's 1879642524.
! site:
! title: An array mapped always, from next to defaultmap(firstprivate: aggregate) is not copied back (fuzz seed 1978)
! end site
