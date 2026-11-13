! fuzz-5 oop sample, AFAR failures reduced by hand: cluster A: the same inside a target data construct
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 2
! observed HSA_XNACK=1: abort: 'present' map type modifier
! observed HSA_XNACK=0: r1= 2
! filed as: fuzz/s1-9443-afar.f90
! legality: offload.engine.rules accept; CCE 19, 20, 21.0.3 and 21.0.4 compile it (data/reports/fuzz5-oop-afar.md)
program p
  implicit none
  integer, parameter :: n = 32
  integer :: a(n), r1
  a = 1
  !$omp target data map(tofrom: a)
  !$omp target map(close, present, tofrom: a)
    a(1) = a(1) + 1
  !$omp end target
  !$omp end target data
  r1 = a(1)
  print '(a,i0)', 'r1= ', r1
end program p
