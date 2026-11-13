program h
  use omp_lib
  implicit none
  integer :: x, i
  integer, allocatable :: a(:)
  allocate(a(8)); a=1
  x=1
  !$omp target map(tofrom:x) map(to:a)
  x = merge(1,0,omp_is_initial_device())
  !$omp end target
  print *, 'A', x
  x=1
  !$omp target map(tofrom:x) map(to:a)
  x = merge(1,0,omp_is_initial_device())
  !$omp end target
  print *, 'B', x
  x=1
  !$omp target map(tofrom:x) map(to:a)
  x = merge(1,0,omp_is_initial_device())
  do i=1,8
    a(i)=2
  end do
  !$omp end target
  print *, 'C', x
end
