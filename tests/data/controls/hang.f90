! Control program (hand-written): legal, never terminates. The target
! region waits for a flag that nothing sets; the RESULT line after it is
! never reached. Used to test the runner's timeout classification.
! The flag `done` is VOLATILE; without it AFAR at -O1 and above deletes the
! side-effect-free spin loop and the program completes.
program hang
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag, spins
  logical :: ok
  logical, volatile :: done
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  done = .false.
  spins = 0
  !$omp target map(to: a, done) map(from: b) map(tofrom: host_flag, spins)
  host_flag = merge(1, 0, omp_is_initial_device())
  do while (.not. done)
    spins = mod(spins + 1, 1000)
  end do
  do i = 1, n
    b(i) = 2*a(i) + 1
  end do
  !$omp end target
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program hang
