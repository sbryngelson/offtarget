! Docs/findings/apps/afar-cce-teams-private-array-nested-parallel-wrong.f90: CONTROL: the same nested parallel do loops;
! the scratch is a mapped array s(0:3, n/4) indexed by the team's iteration, not a private array. Expected and observed on AFAR, CCE
! 19/20/21 and NVHPC 25.11/26.9: bad= 0
program teams_private_array_nested_parallel
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), s(0:3, n/4), i, j, jt, bad, dev
  do i = 1, n
    a(i) = i
  end do
  b = 0
  dev = -1
  !$omp target teams distribute private(j) map(to: a) map(from: b) map(alloc: s) map(tofrom: dev)
  do jt = 1, n, 4
    !$omp parallel do
    do j = 0, 3
      s(j, (jt + 3)/4) = a(jt + j)
    end do
    !$omp end parallel do
    !$omp parallel do
    do j = 0, 3
      b(jt + j) = 2*s(3 - j, (jt + 3)/4) + 1
    end do
    !$omp end parallel do
    if (jt == 1) dev = merge(0, 1, omp_is_initial_device())
  end do
  !$omp end target teams distribute
  bad = 0
  do i = 1, n
    if (b(i) /= 2*(2*(4*((i - 1)/4) + 1) + 3 - i) + 1) bad = bad + 1
  end do
  print '(a,i0,a,i0,a,4(1x,i0))', 'bad= ', bad, ' dev= ', dev, ' b(1:4)=', b(1:4)
end program teams_private_array_nested_parallel
