! fuzz-5 oop sample, AFAR failures reduced by hand: control of B2_fp_reduction
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 8
! observed HSA_XNACK=1: r1= 8
! observed HSA_XNACK=0: r1= 8
! legality: offload.engine.rules accept
program p
  implicit none
  integer, parameter :: n = 8, m = 4
  integer :: i, j, r1
  r1 = -40
  !$omp target map(tofrom: r1)
  !$omp teams reduction(max: r1)
  !$omp distribute
  do i = 1, n
    !$omp parallel
      !$omp do reduction(max: r1)
      do j = 1, m
        r1 = max(r1, i)
      end do
      !$omp end do
    !$omp end parallel
  end do
  !$omp end distribute
  !$omp end teams
  !$omp end target
  print '(a,i0)', 'r1= ', r1
end program p
