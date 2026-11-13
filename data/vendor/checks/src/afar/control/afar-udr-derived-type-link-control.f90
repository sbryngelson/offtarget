module fuzz_dmod
  implicit none
  type :: pair_t
    integer :: x, y
  end type pair_t
  !$omp declare reduction(padd: pair_t: omp_out = &
  !$omp& pair_t(omp_out%x + omp_in%x, omp_out%y + omp_in%y)) &
  !$omp& initializer(omp_priv = pair_t(0, 0))
end module fuzz_dmod
program fuzz_prog
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 64
  type(pair_t) :: rp
  integer :: i
  rp = pair_t(1, 2)
  !$omp parallel do reduction(padd: rp)
  do i = 1, n
    rp = pair_t(rp%x + i, rp%y + mod(i, 3))
  end do
  print '(a,i0)', 'RESULT checksum=', rp%x * 1000 + rp%y
end program fuzz_prog
