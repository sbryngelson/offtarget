program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  logical :: ls, lsref
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  ls = .true.
  lsref = .true.
  do i = 1, n
    lsref = lsref .and. (a(i) /= 17)
  end do
    !$omp target map(to: a) map(from: b) map(tofrom: host_flag) map(tofrom: ls)
      host_flag = merge(1, 0, omp_is_initial_device())
      do i = 1, n
        b(i) = 2*a(i) + 1
        ls = ls .and. (a(i) /= 17)
      end do
    !$omp end target
  ok = all(b == ref) .and. (ls .eqv. lsref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
