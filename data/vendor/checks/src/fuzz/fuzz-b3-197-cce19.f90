program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 16, m = 3
  integer, target :: ib(n)
  integer, target :: ic(n, m)
  integer, allocatable :: as1
  integer, allocatable :: o2(:)
  integer, pointer :: o3(:)
  integer, allocatable :: o4(:)
  integer, target :: o3t(n)
  integer :: i, j, r4a, hf4
  integer(8) :: cs
  allocate(o2(n))
  allocate(o4(n))
  allocate(as1)
  o3 => o3t
  do i = 1, n
    ib(i) = mod(i * 52 + 34, 211) - 23
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 7 * j) * 58 + 25, 101) - 21
    end do
  end do
  as1 = 20
  o2 = 0
  o3 = 0
  o4 = 0
  r4a = 3
  hf4 = 0
  call kp1(as1, ib, ic, o2, o3, o4)
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o3t(i), 8), 2147483629_8)
  end do
  cs = modulo(cs * 31_8 + int(r4a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o4(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf4, 0)
contains
  subroutine kp1(as1, ib, ic, o2, o3, o4)
    integer, intent(inout) :: as1
    integer, intent(inout) :: ib(:)
    integer, intent(in) :: ic(:, :)
    integer, intent(in) :: o2(:)
    integer, intent(inout) :: o3(:)
    integer, intent(inout) :: o4(:)
    !$omp taskgroup task_reduction(+: r4a)
      !$omp target map(tofrom: hf4) in_reduction(+: r4a)
        hf4 = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          o4(i) = mod(iand(o3((mod(((i * 3) + 5), n) + 1)), 1023), 97)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine kp1
end program fuzz_prog
