program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n)
  integer :: i, hf, bad
  a = 0
  hf = 1
  !$omp target nowait depend(out: a) map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      a(i) = 30011
    end do
  !$omp end target
  !$omp target map(to: a(1:n)) nowait depend(in: a)
  !$omp end target
  !$omp taskwait
  bad = count(a /= 30011)
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', bad == 0)
end program p
