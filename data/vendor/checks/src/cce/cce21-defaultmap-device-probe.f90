program h
  use omp_lib
  implicit none
  integer :: x, flag(1)
  integer, allocatable :: a(:)
  allocate(a(8)); a = 1
  x = 1; flag = -1
  !$omp target map(tofrom: x) map(to: a) map(from: flag) defaultmap(to: aggregate)
  x = merge(1, 0, omp_is_initial_device())
  flag(1) = merge(1, 0, omp_is_initial_device())
  !$omp end target
  print *, 'x', x, 'flag', flag(1)
end
