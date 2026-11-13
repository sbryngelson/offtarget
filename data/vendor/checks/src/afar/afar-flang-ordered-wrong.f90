program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: cnt, seq(n)
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  cnt = 0
  seq = -1
  !$omp target map(to: a) map(from: b) map(tofrom: cnt) map(from: seq) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp parallel do default(none) shared(a, b, cnt, seq) ordered
      do i = 1, n
        b(i) = 2*a(i) + 1
        !$omp ordered
          cnt = cnt + 1
          seq(i) = cnt
        !$omp end ordered
      end do
    !$omp end parallel do
  !$omp end target
  ok = all(b == ref) .and. all(2*seq + 1 == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
