program t
  use omp_lib, only: omp_get_thread_num
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: a(:), b(:)
  integer :: ref(n), i, nbad
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i; b(i) = 0; ref(i) = 2*i + 1
  end do
  !$omp target parallel map(to: a) map(from: b)
    !$omp single
      do i = 1, n
        b(i) = 2*a(i) + 1
      end do
    !$omp end single
  !$omp end target parallel
  nbad = count(b /= ref)
  print *, 'single bad=', nbad
end program
