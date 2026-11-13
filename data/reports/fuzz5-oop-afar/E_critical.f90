! fuzz-5 oop sample, AFAR failures reduced by hand: cluster E: unnamed critical in a worksharing loop of target parallel (lost updates)
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 256
! observed HSA_XNACK=1: r1= 0
! observed HSA_XNACK=0: r1= 0
! control (one change, correct): E_ctl_atomic.f90 (atomic update instead of critical)
! filed as: fuzz/1936-afar.f90
! legality: offload.engine.rules accept; no second front end (CCE ICEs on critical, NVHPC does not support it)
program p
  implicit none
  integer, parameter :: n = 256
  integer :: i, r1
  r1 = 0
  !$omp target parallel map(tofrom: r1)
    !$omp do
    do i = 1, n
        !$omp critical
        r1 = ieor(r1, i)
        !$omp end critical
    end do
    !$omp end do
  !$omp end target parallel
  print '(a,i0)', 'r1= ', r1
end program p
