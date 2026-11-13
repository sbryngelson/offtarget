program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: b(64), host_flag, i, c
  b = 0
  host_flag = 1
  c = 1
  !$omp target map(from: b) map(tofrom: host_flag) defaultmap(firstprivate)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, 64
      b(i) = i + c
    end do
  !$omp end target
  print *, 'sum', sum(b), 'host_flag', host_flag
end program p
