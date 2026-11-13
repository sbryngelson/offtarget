program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: s, sref
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  s = 0
  sref = 0
  do i = 1, n
    sref = sref + a(i)
  end do
  !$omp target map(to: a) map(from: b) map(tofrom: host_flag) map(tofrom: s)
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp parallel default(none) shared(a, b, s)
      !$omp do reduction(+: s)
        do i = 1, n
          b(i) = 2*a(i) + 1
          s = s + a(i)
        end do
      !$omp end do
    !$omp end parallel
  !$omp end target
  ok = all(b == ref) .and. (s == sref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
