program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), b(n), i, hf, bad
  integer(8) :: r(n), ref(n)
  do i = 1, n
    a(i) = mod(i * 54 + 44, 101) - 50
    b(i) = mod(i * 53 + 27, 211) - 46
  end do
  do i = 1, n
    ref(i) = int(a(i), 8) * int(b(i), 8)
  end do
  r = 0
  hf = 1
  !$omp target map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      r(i) = int(a(i), 8) * int(b(i), 8)
    end do
  !$omp end target
  bad = count(r /= ref)
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', bad == 0)
end program p
