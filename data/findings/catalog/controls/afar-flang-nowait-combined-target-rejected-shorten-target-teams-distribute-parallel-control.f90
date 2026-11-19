! Control of afar-flang-nowait-combined-target-rejected.f90: shorten target teams distribute parallel do to target teams
!   distribute at line 9; one change from the reduction; passes on afar244/1, afar244/0.
! Every step passed the legality rules witness (offload.engine.prerun rules); the front-end witness (offload.engine.prerun.check)
!   is still to run on Tuolumne.
program repro
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i, on_host
  a = [(i, i = 1, n)]
  b = 0
  on_host = 1
  !$omp target teams distribute map(to: a) map(tofrom: b, on_host) nowait
  do i = 1, n
    b(i) = 2*a(i)
    if (i == 1) on_host = merge(1, 0, omp_is_initial_device())
  end do
  !$omp end target teams distribute
  !$omp taskwait
  print '(a,i0,a,a)', 'RESULT ran_on_host=', on_host, ' check=', merge('pass', 'fail', all(b == &
      & 2*a))
end program repro
