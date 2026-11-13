program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: a(:)
  integer :: i, k, host_flag
  do k = 1, 4
    allocate(a(n))
    a = [(i, i = 1, n)]
    host_flag = 1
    select case (k)
    case (1)
      !$omp target map(alloc: a) map(tofrom: host_flag)
        host_flag = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          a(i) = -i
        end do
      !$omp end target
    case (2)
      !$omp target map(alloc: a) map(tofrom: host_flag) defaultmap(tofrom)
        host_flag = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          a(i) = -i
        end do
      !$omp end target
    case (3)
      !$omp target map(to: a) map(tofrom: host_flag)
        host_flag = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          a(i) = -i
        end do
      !$omp end target
    case (4)
      !$omp target map(to: a) map(tofrom: host_flag) defaultmap(tofrom)
        host_flag = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          a(i) = -i
        end do
      !$omp end target
    end select
    print '(a,i0,a,i0,a,i0)', 'region ', k, ': host_flag=', host_flag, &
      ' host a unchanged: ', count(a == [(i, i = 1, n)])
    deallocate(a)
  end do
end program p
