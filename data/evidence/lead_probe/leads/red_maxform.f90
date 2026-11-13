! lead 1 follow-up: the Fortran max form (l = max(l, i * 40))
program redm
  use omp_lib
  implicit none
  integer(8) :: l
  integer :: i, dev
  l = 0
  dev = -1
  !$omp target teams distribute reduction(max: l) map(tofrom: l)
  do i = 1, 64
    l = max(l, int(i, 8) * 40)
  end do
  !$omp target map(tofrom: dev)
  dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  print '(a,i0,a,i0)', 'l= ', l, ' dev= ', dev
end program redm
