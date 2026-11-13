! OpenMP 5.0: linear(ref(x)) on declare simd with x a scalar dummy argument.
! 5.0 §2.19.4.6 p.293: "The ref or uval modifier can only be used if the
! list-item is a dummy argument without the VALUE attribute." and "If the
! ref modifier is specified, variables with the ALLOCATABLE attribute,
! assumed-shape arrays and polymorphic variables may not appear in the
! linear clause." -- so a scalar dummy is the legal 5.0 form.
! (5.2 §5.4.6 p.119 reverses this: with ref the item must be polymorphic,
! assumed-shape or ALLOCATABLE.) Expected with -fopenmp-version=50: accepted.
module m
contains
  integer function lf(x)
    !$omp declare simd(lf) linear(ref(x))
    integer, intent(in) :: x
    lf = 2*x + 1
  end function lf
end module m
program p
  use m
  implicit none
  integer :: i, b(4)
  do i = 1, 4
    b(i) = lf(i)
  end do
  print *, b
end program p
! site:
! disposition: out-of-scope host-only construct (declare simd on a host procedure, no target region): outside the device-offload
! + scope; the README does not mark it out of scope
! end site
