! fuzz-5 oop sample, AFAR failures reduced by hand: cluster B: parallel firstprivate(i) nested in the distribute loop of target teams distribute
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 224
! observed HSA_XNACK=1: r1= 9 (writes lost)
! observed HSA_XNACK=0: memory access fault
! control (one change, correct): B_ctl_combined.f90 (firstprivate(i) removed)
! filed as: fuzz/650-afar.f90
! legality: offload.engine.rules accept; CCE 19, 20, 21.0.3 and 21.0.4 compile it (data/reports/fuzz5-oop-afar.md)
program p
  implicit none
  integer, parameter :: n = 8, m = 4
  integer :: o(n, m)
  integer :: i, j, r1
  o = 0
  !$omp target teams distribute map(tofrom: o)
  do i = 1, n
    !$omp parallel firstprivate(i)
      !$omp do
      do j = 1, m
        o(i, j) = i + j
      end do
      !$omp end do
    !$omp end parallel
  end do
  !$omp end target teams distribute
  r1 = sum(o)
  print '(a,i0)', 'r1= ', r1
end program p
