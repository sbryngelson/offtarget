program teams
  use omp_lib
  implicit none
  integer, parameter :: n = 100000
  real(8), allocatable :: a(:)
  real(8) :: s, want
  integer :: i
  logical :: on_host
  allocate(a(n))
  do i = 1, n
    a(i) = (i - 1) * 0.5d0
  end do
  s = 0d0
  on_host = .true.
  !$omp target teams distribute parallel do reduction(+:s) map(to:a) map(tofrom:on_host)
  do i = 1, n
    if (i == 1) on_host = omp_is_initial_device()
    s = s + a(i)
  end do
  want = 0.5d0 * dble(n) * dble(n - 1) / 2d0
  if (s == want .and. .not. on_host) then
    print '(a,f14.1,a,l1,a)', 'teams.f90 sum=', s, ' on_host=', on_host, ' PASS'
  else
    print '(a,f14.1,a,l1,a)', 'teams.f90 sum=', s, ' on_host=', on_host, ' FAIL'
    error stop 1
  end if
end program teams
