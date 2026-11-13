! fuzz-5 oop sample, AFAR failures reduced by hand: cluster C: atomic add of mod(i, 97) (integer), allocatable array written
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 408
! observed HSA_XNACK=1: memory access fault
! observed HSA_XNACK=0: r1= 408
! control (one change, correct): C_int_const_alloc.f90 (right-hand side 1)
! filed as: fuzz/b1-231-afar.f90
! legality: offload.engine.rules accept; CCE 19, 20, 21.0.3 and 21.0.4 compile it (data/reports/fuzz5-oop-afar.md)
program p
  implicit none
  integer, parameter :: n = 16, m = 3
  integer :: ia(n), i, j
  integer :: r1
  integer, allocatable :: o1(:, :)
  do i = 1, n
    ia(i) = mod(i * 7, 11)
  end do
  allocate(o1(n, m))
  o1 = 0
  r1 = 0
  !$omp target map(tofrom: r1)
  !$omp teams
  !$omp distribute
  do i = n, 1, -1
    !$omp parallel
      !$omp do
      do j = 1, m
        o1(i, j) = 0
        !$omp atomic
        r1 = r1 + mod(i, 97)
      end do
      !$omp end do
    !$omp end parallel
  end do
  !$omp end distribute
  !$omp end teams
  !$omp end target
  print '(a,i0)', 'r1= ', int(r1)
end program p
