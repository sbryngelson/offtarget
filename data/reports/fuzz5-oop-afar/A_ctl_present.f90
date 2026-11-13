! fuzz-5 oop sample, AFAR failures reduced by hand: control of A_close_present: present without close
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 2
! observed HSA_XNACK=1: r1= 2
! observed HSA_XNACK=0: r1= 2
! legality: offload.engine.rules accept
program p
  implicit none
  integer, parameter :: n = 32
  integer :: a(n)
  integer :: r1
  a = 1
  !$omp target enter data map(to: a)
  !$omp target map(present, tofrom: a)
    a(1) = a(1) + 1
  !$omp end target
  !$omp target exit data map(from: a)
  r1 = a(1)
  print '(a,i0)', 'r1= ', r1
end program p
