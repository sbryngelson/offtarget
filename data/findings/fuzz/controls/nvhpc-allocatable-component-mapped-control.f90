program p
  implicit none
  type :: rec_t
    integer :: a(16)
    integer, allocatable :: q(:)
  end type rec_t
  type(rec_t) :: dr
  integer :: o(16), i
  allocate(dr%q(16))
  do i = 1, 16
    dr%a(i) = i
    dr%q(i) = 10 * i
  end do
  o = 0
  !$omp target map(from: o) map(to: dr%q)
  do i = 1, 16
    o(i) = dr%q(i)
  end do
  !$omp end target
  print '(a,i0)', 'sum= ', sum(o)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(o) == 1360)
end program p
