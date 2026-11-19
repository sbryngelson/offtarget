! # Finding (reduce): amdflang 24.4.0 stops with an error on reduction(-:) in an OpenMP 5.2 program ("The minus reduction
! # operator is deprecated since OpenMP v5.2"); a deprecated feature is still part of 5.2
!
! - toolchains and modes that fail: afar244 (AFAR 24.4.0); modes: unified, copy; -O2
! - build: amdflang -fopenmp --offload-arch=gfx942 -O2
! - failure: rejected
! - observed: `site-catalog--afar-flang-deprecated-minus-reduction-rejected.f90:33:81: error: The minus reduction operator is
!   deprecated since OpenMP v5.2`; identical signature on 2 of 2 failing cells
! - expected: compiles and runs to completion, printing `RESULT ran_on_host=0 check=pass`
! - rule: OpenMP 5.2 §5.5.1 p.124 l.22-23, Fortran: "A reduction identifier is either a base language identifier, or a user-defined
!   operator, or one of the following operators: +, - (deprecated), *, .and., .or., .eqv., .neqv., or one of the"; and 5.2 §1.2.7
!   p.20 l.21-22: deprecated is "the property that it is normative in the current specification but is considered obsolescent
!   and will be removed in the future."
! - other families: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the file correctly (site
!   rows, check case site-catalog--afar-flang-deprecated-minus-reduction-rejected); afar (AFAR 24.3.0) fail it another way, e.g.
!   `site-catalog--afar-flang-deprecated-minus-reduction-rejected.f90:33:71: error: The minus reduction operator is deprecated since
!   OpenMP 5.2 and is not `
! - legality: legal by reading: reduction(-: s) on a combined target teams distribute parallel do with s mapped tofrom and the
!   loop updating s = s - a(i); the - operator is a normative, deprecated reduction identifier of 5.2. The rules witness
!   (offload.engine.prerun) accepts it, and another family's front end, CCE ftn 19, 20 and 21, compiles and runs it correctly
!   (site rows). A warning would be conforming; an error is not
! - releases: AFAR 24.3.0 fails it another way; AFAR 24.4.0 fails it the same way
program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: s, sref
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  s = 0
  sref = 0
  do i = 1, n
    sref = sref - a(i)
  end do
  !$omp target teams distribute parallel do map(to: a) map(from: b) map(tofrom: s) &
  !$omp& map(tofrom: host_flag) default(none) shared(a, b, host_flag) reduction(-: s)
    do i = 1, n
      b(i) = 2*a(i) + 1
      s = s - a(i)
      if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
    end do
  !$omp end target teams distribute parallel do
  ok = all(b == ref) .and. (s == sref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog

! site:
! title: AFAR 24.4.0: deprecated reduction(-:) rejected at OpenMP 5.2
! summary: AFAR 24.4.0 stops with an error on a reduction(-:) clause in an OpenMP 5.2 program, although 5.2 only deprecates the
! + minus operator and it remains normative; CCE compiles and runs the program.
! end site
