! Audit, candidate 2 (Fortran), CONTROL (explicit map): lastprivate on the combined target
! construct implies map(tofrom) (OpenMP 5.0 §2.14 p.218; 5.2 §17.2 p.339).
! Expected: l= 2560 dev= 1
program lastprivate_combined
  use omp_lib
  implicit none
  integer(8) :: l
  integer :: i, dev
  l = 0
  dev = -1
  !$omp target parallel do lastprivate(l) map(tofrom: l)
  do i = 1, 64
    l = int(i, 8) * 40
  end do
  !$omp end target parallel do
  !$omp target map(tofrom: dev)
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  print '(a,i0,a,i0)', 'l= ', l, ' dev= ', dev
end program lastprivate_combined
