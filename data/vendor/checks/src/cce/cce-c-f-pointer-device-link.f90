program gen_prog
  use omp_lib, only: omp_is_initial_device
  use, intrinsic :: iso_c_binding, only: c_ptr, c_loc, c_f_pointer
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  type(c_ptr) :: pa, pb
  integer, pointer :: pp(:), qq(:)
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  pa = c_loc(a)
  pb = c_loc(b)
  !$omp target data map(to: a) map(from: b) use_device_ptr(pa, pb)
    !$omp target is_device_ptr(pa, pb) private(pp, qq) map(tofrom: host_flag)
      host_flag = merge(1, 0, omp_is_initial_device())
      call c_f_pointer(pa, pp, [n])
      call c_f_pointer(pb, qq, [n])
      do i = 1, n
        qq(i) = 2*pp(i) + 1
      end do
    !$omp end target
  !$omp end target data
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
