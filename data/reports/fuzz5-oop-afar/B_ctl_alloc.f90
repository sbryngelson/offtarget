! fuzz-5 oop sample, AFAR failures reduced by hand: control of B_fp_alloc
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 224
! observed HSA_XNACK=1: r1= 224
! observed HSA_XNACK=0: r1= 224
! legality: offload.engine.rules accept
program p
  implicit none
  integer, parameter :: n = 8, m = 4
  integer, allocatable :: o(:, :)
  integer :: i, j, r1
  allocate(o(n, m))
  o = 0
  !$omp target map(tofrom: o)
  !$omp teams
  !$omp distribute
  do i = 1, n
    !$omp parallel
      !$omp do
      do j = 1, m
        o(i, j) = i + j
      end do
      !$omp end do
    !$omp end parallel
  end do
  !$omp end distribute
  !$omp end teams
  !$omp end target
  r1 = sum(o)
  print '(a,i0)', 'r1= ', r1
end program p
