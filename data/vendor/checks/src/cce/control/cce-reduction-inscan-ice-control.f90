program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: s
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = i*(i + 1)/2
  end do
  host_flag = 1
  s = 0
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp parallel do default(none) shared(a, b) reduction(inscan, +: s)
      do i = 1, n
        s = s + a(i)
        !$omp scan inclusive(s)
        b(i) = s
      end do
    !$omp end parallel do
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
