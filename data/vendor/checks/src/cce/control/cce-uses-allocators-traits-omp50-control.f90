program p
  use omp_lib
  implicit none
  integer, parameter :: n = 8
  integer :: a(n), b(n), i, t
  integer(omp_allocator_handle_kind) :: my_alloc
  type(omp_alloctrait), parameter :: my_traits(1) = &
    [omp_alloctrait(omp_atk_alignment, 64)]
  a = [(i, i = 1, n)]
  !$omp target map(to: a) map(from: b) uses_allocators(traits(my_traits): my_alloc)
  !$omp parallel do private(t) allocate(my_alloc: t) default(none) shared(a, b, my_alloc)
  do i = 1, n
    t = 2*a(i)
    b(i) = t + 1
  end do
  !$omp end target
  print *, b
end program p
