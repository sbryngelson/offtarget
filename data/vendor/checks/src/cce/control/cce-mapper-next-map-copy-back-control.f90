program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  type :: dt
    integer :: v
  end type dt
  !$omp declare mapper(mm: dt :: q) map(to: q%v)
  integer :: host_flag, b(4)
  type(dt) :: s
  s%v = 1
  host_flag = 1
  b = 0
  !$omp target map(tofrom: host_flag) map(from: b) map(mapper(mm), tofrom: s)
    host_flag = merge(1, 0, omp_is_initial_device())
    b = 2 + s%v
    s%v = 7
  !$omp end target
  print *, 'host_flag=', host_flag, ' b1=', b(1), ' sv=', s%v
end program p
