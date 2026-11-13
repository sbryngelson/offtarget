! OpenMP 5.0 §2.12.5 p.170: uses_allocators(allocator[(allocator-traits-array)]).
! The allocator handle is shared on a parallel do nested in the target
! region (a different construct, so 5.0 §2.12.5 p.175 does not forbid it).
! Expected: compiles and prints 2*i+1. The same program with the 5.2 form
! uses_allocators(traits(my_traits): my_alloc) compiles on CCE 19/20/21.
program p
  use omp_lib
  implicit none
  integer, parameter :: n = 8
  integer :: a(n), b(n), i, t
  integer(omp_allocator_handle_kind) :: my_alloc
  type(omp_alloctrait), parameter :: my_traits(1) = &
    [omp_alloctrait(omp_atk_alignment, 64)]
  a = [(i, i = 1, n)]
  !$omp target map(to: a) map(from: b) uses_allocators(my_alloc(my_traits))
  !$omp parallel do private(t) allocate(my_alloc: t) default(none) shared(a, b, my_alloc)
  do i = 1, n
    t = 2*a(i)
    b(i) = t + 1
  end do
  !$omp end target
  print *, b
end program p
! site:
! title: ftn: OpenMP 5.0 form uses_allocators(my_alloc(my_traits)) rejected as a function reference (ftn-451)
! control: ../vendor/checks/src/cce/control/cce-uses-allocators-traits-omp50-control.f90 the OpenMP 5.2 spelling
! + uses_allocators(traits(my_traits): my_alloc)
! end site
