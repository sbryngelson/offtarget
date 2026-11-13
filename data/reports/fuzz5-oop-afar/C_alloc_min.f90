! fuzz-5 oop sample, AFAR failures reduced by hand: cluster C: atomic update whose right-hand side depends on i, in a parallel do nested in the distribute loop, with an allocatable array written
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 0
! observed HSA_XNACK=1: memory access fault (write access to a read-only page)
! observed HSA_XNACK=0: r1= 0
! control (one change, correct): C_fixed_min.f90 (explicit-shape array)
! filed as: afar-xnack1-atomic-min-nested-parallel.f90, fuzz/b1-183-afar.f90, fuzz/b1-231-afar.f90
! legality: offload.engine.rules accept; CCE 19, 20, 21.0.3 and 21.0.4 compile it (data/reports/fuzz5-oop-afar.md)
program p
  implicit none
  integer, parameter :: n = 8, m = 4
  integer, allocatable :: o(:, :)
  integer :: i, j, r1
  allocate(o(n, m))
  o = 0
  r1 = 7
  !$omp target map(tofrom: r1)
  !$omp teams
  !$omp distribute
  do i = 1, n
    !$omp parallel
      !$omp do
      do j = 1, m
        o(i, j) = 0
        !$omp atomic
        r1 = min(r1, mod(i, 5))
      end do
      !$omp end do
    !$omp end parallel
  end do
  !$omp end distribute
  !$omp end teams
  !$omp end target
  print '(a,i0)', 'r1= ', r1
end program p
