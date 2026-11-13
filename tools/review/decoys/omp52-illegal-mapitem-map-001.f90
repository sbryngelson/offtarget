program p
  use omp_lib, only: omp_is_initial_device
  use, intrinsic :: iso_c_binding, only: c_loc
  implicit none
  type :: dt
    integer :: v
  end type dt
  !$omp declare mapper(mm: dt :: q) map(to: q%v)
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  type(dt) :: s
  logical :: pres, shared_mem
  integer :: zc(1)
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  s%v = 1
  pres = .true.
  zc = 0
  !$omp target map(to: zc)
    zc(1) = 1
  !$omp end target
  shared_mem = zc(1) == 1
  !$omp target map(to: a) map(from: b) map(mapper(mm), tofrom: s) map(to: s) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      b(i) = 2*a(i) + s%v
    end do
    s%v = 7
  !$omp end target
  if (.not. shared_mem) pres = pres .and. (s%v == 1)
  ok = all(b == ref) .and. pres
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program p
