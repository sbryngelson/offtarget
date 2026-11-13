! fuzz-5 oop sample, AFAR failures reduced by hand: control of A_derived
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 4
! observed HSA_XNACK=1: r1= 4
! observed HSA_XNACK=0: r1= 4
! legality: offload.engine.rules accept
program p
  implicit none
  integer, parameter :: n = 32
  type :: rec_t
    integer :: s = 3
    integer :: v(n)
  end type rec_t
  type(rec_t) :: dr
  integer :: r1
  dr%v = 1
  !$omp target enter data map(to: dr)
  !$omp target map(present, tofrom: dr)
    dr%v(1) = dr%v(1) + dr%s
  !$omp end target
  !$omp target exit data map(from: dr)
  r1 = dr%v(1)
  print '(a,i0)', 'r1= ', r1
end program p
