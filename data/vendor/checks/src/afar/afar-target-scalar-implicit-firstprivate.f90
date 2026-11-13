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
