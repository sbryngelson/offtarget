! Control of fuzz/par-s1-2082-gcc_g90.f90: o1 a complex array instead of a pointer to one (compiles; correct on gcc_g90 and
! gcc_sm80).
program cptr_store
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 24
  integer :: ic(n, 2), i, host_flag, bad
  ! control: o1 a complex array, not a pointer to one
  complex :: o1(n)
  do i = 1, n
    ic(i, 1) = 0
    ic(i, 2) = mod((i + 14) * 24 + 22, 101) - 1
  end do
  o1 = 0
  host_flag = 1
  !$omp target map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = n, 1, -1
      o1(i) = ic(i, 2)
    end do
  !$omp end target
  bad = 0
  do i = 1, n
    if (o1(i) /= cmplx(ic(i, 2), 0.0)) bad = bad + 1
  end do
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program cptr_store
