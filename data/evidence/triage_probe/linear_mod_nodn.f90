! id: omp52-probe-linear_mod_nodn
! probe: OpenMP 5.2 linear modifier syntax without default(none) in a target region
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i, x, host_flag
  a = [(i, i = 1, n)]
  b = 0
  x = 3
  host_flag = 1
  !$omp target map(to: a) map(from: b) map(tofrom: x, host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp parallel do linear(x: val, step(1))
    do i = 1, n
      b(i) = 2*a(i) + 1 + (x - (i + 2))
      x = x + 1
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', all(b == 2*a + 1) .and. x == n + 3)
end program p
