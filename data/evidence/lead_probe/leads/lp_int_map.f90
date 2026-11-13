! lead 2 follow-up: the Fortran form, a default-kind integer
program lpi
  use omp_lib
  implicit none
  integer :: lp, i, dev
  lp = -1
  dev = -1
  !$omp target teams distribute parallel do lastprivate(lp) map(tofrom: lp)
  do i = 1, 64
    lp = 3 * i
  end do
  !$omp target map(tofrom: dev)
  dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  print '(a,i0,a,i0)', 'lp= ', lp, ' dev= ', dev
end program lpi
