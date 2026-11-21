program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer(8) :: x(n)
  integer(8) :: r(n), ref(n)
  integer :: i, hf, bad
  do i = 1, n
    x(i) = int(i, 8) * 1000000007_8 + 12_8
    ref(i) = mod(x(i), 1000003_8)
  end do
  r = 0
  hf = 1
  !$omp target map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      r(i) = mod(x(i), 1000003_8)
    end do
  !$omp end target
  bad = count(r /= ref)
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', bad == 0)
end program p

