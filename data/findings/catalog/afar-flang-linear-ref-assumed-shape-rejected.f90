! # Finding (reduce): amdflang 24.4.0 rejects linear(x: ref) on declare simd for an assumed-shape dummy, the list item the
! # specification requires ("must not be a polymorphic variable, an assumed-shape array, or ... ALLOCATABLE")
!
! - toolchains and modes that fail: afar244 (AFAR 24.4.0); modes: unified, copy; -O2
! - build: amdflang -fopenmp --offload-arch=gfx942 -O2
! - failure: rejected
! - observed: `site-catalog--afar-flang-linear-ref-assumed-shape-rejected.f90:18:37: error: The list item `x` specified with the REF
!   'linear-modifier' must not be a `; identical signature on 2 of 2 failing cells
! - expected: compiles and runs to completion, printing `RESULT ran_on_host=0 check=pass`
! - rule: OpenMP 5.2 §5.4.6 p.119 l.22-23: "If linear-modifier is ref, list items must be polymorphic variables, assumed-shape
!   arrays, or variables with the ALLOCATABLE attribute." The list item x is an assumed-shape dummy argument without the VALUE
!   attribute on a declare simd directive, the only place the ref modifier is allowed (same section): the compiler's message states
!   the opposite of the restriction
! - same-compiler control: controls/afar-flang-linear-ref-assumed-shape-rejected-delete-clause-linear-x-ref-control.f90 (one change
!   from this file; correct on afar244 (AFAR 24.4.0); rows results/reduce/linref/rows.jsonl)
! - other families: cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the file correctly (site rows, check case
!   site-catalog--afar-flang-linear-ref-assumed-shape-rejected); afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2) fail it
!   another way, e.g. `loc("site-catalog--afar-flang-linear-ref-assumed-shape-rejected.f90":18:13): error: not yet implemented:
!   omp.declare_simd`
! - legality: legal by reading: linear(x: ref) on the declare simd directive of a function whose dummy x is assumed-shape and has
!   no VALUE attribute meets every restriction of 5.2 §5.4.6; the rules witness (offload.engine.prerun) accepts it, and another
!   family's front end, CCE ftn 21, compiles and runs it correctly (site rows). AFAR 24.3.0 does not implement the clause
! - releases: AFAR 24.3.0 fails it another way; AFAR 24.4.0 fails it the same way
module gen_mod
  implicit none
  contains
    integer function lf(x)
      !$omp declare target
      !$omp declare simd(lf) linear(x: ref)
      integer, intent(in) :: x(:)
      lf = 2*x(1) + 1
    end function lf
end module gen_mod

program gen_prog
  use omp_lib, only: omp_is_initial_device
  use gen_mod
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  !$omp target map(to: a) map(from: b) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      b(i) = lf(a(i:i))
    end do
  !$omp end target
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog

! site:
! title: AFAR 24.4.0: linear(ref) rejected for an assumed-shape dummy
! summary: AFAR 24.4.0 rejects linear(x: ref) on declare simd when x is an assumed-shape dummy, saying the list item must not be
! + assumed-shape, where OpenMP 5.2 requires ref list items to be polymorphic, assumed-shape or allocatable.
! control: catalog/controls/afar-flang-linear-ref-assumed-shape-rejected-delete-clause-linear-x-ref-control.f90 one change from the
! + finding; correct on afar244
! end site
