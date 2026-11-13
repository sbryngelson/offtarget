! Canary (hand-written): deliberately racy. Every iteration of the
! target teams distribute parallel do loop updates the shared scalar s
! without a reduction clause: a data race (OpenMP 5.2 §1.4.1 p.27, the
! result is unspecified). The pre-run check (offload.engine.prerun) must refuse
! it; it is never compiled or run.
program racy
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 1024
  integer :: a(n), i, s, host_flag
  do i = 1, n
    a(i) = i
  end do
  s = 0
  host_flag = 1
  !$omp target teams distribute parallel do map(to: a) map(tofrom: s, host_flag)
  do i = 1, n
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
    s = s + a(i)
  end do
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', &
    merge('pass', 'fail', s == n * (n + 1) / 2)
end program racy
