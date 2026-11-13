program p
  use omp_lib, only: omp_get_team_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: cnt(n, 4), tm
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  cnt = 0
  !$omp target parallel map(to: a) map(from: b) map(tofrom: cnt) map(tofrom: host_flag) &
  !$omp& private(tm)
    if (omp_get_team_num() == 0) then
      !$omp parallel num_threads(1)
        host_flag = merge(1, 0, omp_is_initial_device())
      !$omp end parallel
    end if
    tm = omp_get_team_num()
    !$omp distribute
      do i = 1, n
        b(i) = 2*a(i) + 1
        cnt(i, tm + 1) = cnt(i, tm + 1) + 1
      end do
    !$omp end distribute
  !$omp end target parallel
  ok = all(b == ref) .and. all(sum(cnt, dim=2) == 1)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program p
