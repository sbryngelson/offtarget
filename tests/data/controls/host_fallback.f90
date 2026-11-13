! Control program (hand-written): legal, and the target region runs on the
! host because of if(.false.) (OpenMP 5.2 §3.4 / 6.0 §5.5: a false if
! clause on target executes the region on the host device). Expected
! output on every toolchain: RESULT ran_on_host=1 check=pass
program host_fallback
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 0
  !$omp target if(.false.) map(to: a) map(from: b) map(tofrom: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  do i = 1, n
    b(i) = 2*a(i) + 1
  end do
  !$omp end target
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program host_fallback
