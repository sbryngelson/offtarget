! Control of harvest/gcc-teams-simd-matmul-allocatable-ice.f90: the product as explicit loops in the same construct
! (compiles; correct on gcc_g90 and gcc_sm80).
program matmul_teams_simd
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: i, j, k, l, host_flag
  real, allocatable :: a(:,:,:), b(:,:,:), c(:,:,:)
  allocate(a(5,7,16), b(7,6,16), c(5,6,16))
  a = 1.0
  b = 2.0
  c = 0.0
  host_flag = 1
  !$omp target teams distribute parallel do simd map(tofrom: a, b, c, host_flag)
  do k = 1, 16
    if (k == 1) host_flag = merge(1, 0, omp_is_initial_device())
    do j = 1, 6
      do i = 1, 5
        do l = 1, 7
          c(i,j,k) = c(i,j,k) + a(i,l,k)*b(l,j,k)
        end do
      end do
    end do
  end do
  ! every element is 7 * (1.0 * 2.0)
  print '(a,f8.1)', 'sum= ', sum(c)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', sum(c) == 5*6*16*14.0)
end program matmul_teams_simd
