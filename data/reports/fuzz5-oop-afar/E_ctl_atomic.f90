! fuzz-5 oop sample, AFAR failures reduced by hand: control of E_critical
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 256
! observed HSA_XNACK=1: r1= 256
! observed HSA_XNACK=0: r1= 256
! legality: offload.engine.rules accept
program p
  implicit none
  integer, parameter :: n = 256
  integer :: i, r1
  r1 = 0
  !$omp target parallel map(tofrom: r1)
    !$omp do
    do i = 1, n
        !$omp atomic update
        r1 = ieor(r1, i)
    end do
    !$omp end do
  !$omp end target parallel
  print '(a,i0)', 'r1= ', r1
end program p
