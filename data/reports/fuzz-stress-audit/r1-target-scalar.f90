! Audit, candidate 1: a scalar with the TARGET attribute referenced
! in a target region is implicitly map(tofrom) (OpenMP 5.0 §2.19.7 p.314,
! 5.2 §5.8.1 p.148, 6.0 §7.9.3 p.276: "If a scalar variable has the TARGET,
! ALLOCATABLE or POINTER attribute then it is treated as if it had appeared
! in a map clause with a map-type of tofrom"). Expected: rd= 101 s= 203 dev= 1
program target_scalar_tofrom
  use omp_lib
  implicit none
  integer(8), target :: s
  integer(8) :: rd
  integer :: dev
  s = 101
  rd = -1
  dev = -1
  !$omp target map(tofrom: rd, dev)
    rd = s
    s = 2 * s + 1
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  print '(a,i0,a,i0,a,i0)', 'rd= ', rd, ' s= ', s, ' dev= ', dev
end program target_scalar_tofrom
