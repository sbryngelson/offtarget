! Control of stress/gcc-declare-target-allocatable-component-ice.f90: the same program without the declare target
! directive (compiles; correct on gcc_g90 and gcc_sm80).
module dt_m
  implicit none
  type :: holder
    integer, allocatable :: v1(:)
  end type holder
  type(holder) :: gq
end module dt_m

program declared_alloc_component
  use omp_lib, only: omp_is_initial_device
  use dt_m
  implicit none
  integer :: out(64), i, host_flag
  allocate(gq%v1(64))
  gq%v1 = [(3*i, i = 1, 64)]
  !$omp target enter data map(to: gq%v1)
  out = 0
  host_flag = 1
  !$omp target teams distribute parallel do map(tofrom: out, host_flag)
  do i = 1, 64
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
    out(i) = gq%v1(i) + 1
  end do
  !$omp target exit data map(delete: gq%v1)
  print '(a,i0)', 'sum= ', sum(out)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', sum(out) == 3*64*65/2 + 64)
end program declared_alloc_component
