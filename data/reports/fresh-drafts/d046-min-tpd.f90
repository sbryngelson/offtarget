! Fresh-046 variant: as d046-min.f90 on target parallel do (no teams).
! Expected: b(1) 1 b(64) 64 dev 1
module ctl
  implicit none
  logical :: on = .true.
end module ctl

program p
  use omp_lib, only: omp_is_initial_device
  use ctl
  implicit none
  integer :: b(64), i, dev
  b = 0
  dev = -1
  !$omp target parallel do map(tofrom: b, dev) if (on)
  do i = 1, 64
    b(i) = i
    if (i == 1) dev = merge(0, 1, omp_is_initial_device())
  end do
  print *, 'b(1)', b(1), 'b(64)', b(64), 'dev', dev
end program p
