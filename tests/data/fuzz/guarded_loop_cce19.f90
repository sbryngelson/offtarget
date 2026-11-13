! Fixture for offload.engine.fuzz_min: the CCE target-parallel
! guarded-loop bug (data/findings/cce19-target-parallel-guarded-loop.f90)
! in the fuzz program format, padded with two unrelated kernels, extra
! clauses and statements for the minimizer to remove. Legal OpenMP 5.2.
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 64, m = 4
  integer, allocatable :: ia(:)
  integer :: ib(n)
  integer, allocatable :: o1(:)
  integer :: o2(n)
  integer, allocatable :: o3(:)
  integer :: i, j, jj, p1, r1a, hf1, hf2, hf3
  integer(8) :: cs
  allocate(ia(n))
  allocate(o1(n))
  allocate(o3(n))
  do i = 1, n
    ia(i) = mod(i * 37 + 11, 97) - 40
  end do
  do i = 1, n
    ib(i) = mod(i * 13 + 5, 101) - 50
  end do
  o1 = 0
  o2 = 0
  o3 = 0
  p1 = 3
  r1a = 0
  hf1 = 0
  hf2 = 0
  hf3 = 0
  ! fuzz: kernels
  !$omp target teams distribute parallel do map(to: ia) map(from: o1) reduction(+: r1a) &
  !$omp& num_teams(4)
  do i = 1, n
    if (i == 1) hf1 = merge(1, 0, omp_is_initial_device())
    o1(i) = mod(ia(i) * 3 + p1, 97)
    r1a = r1a + mod(ib(i), 7)
  end do
  !$omp end target teams distribute parallel do
  !$omp target parallel map(to: ia, ib) map(from: o2) map(tofrom: hf2) proc_bind(close)
    if (omp_get_thread_num() == 0) then
      hf2 = merge(1, 0, omp_is_initial_device())
      do i = 1, n
        o2(i) = 2 * ia(i) + 1
      end do
    end if
  !$omp end target parallel
  !$omp target map(to: o1, ib) map(tofrom: o3, hf3)
    hf3 = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      o3(i) = o1(i) - ib(i)
    end do
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o3(i), 8), 2147483629_8)
  end do
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, hf2, hf3, 0)
end program fuzz_prog
