module fuzz_dmod
  implicit none
  integer, parameter :: nm = 16
  integer, private :: kk
  type :: gp_t
  end type gp_t
  type :: mt_t
    integer :: a(nm)
  end type mt_t
  type :: pair_t
  end type pair_t
  integer :: gtab(nm) = [(mod(kk * 27 + 46, 1009) - 350, kk = 1, nm)]
  type(gp_t) :: gs
  !$omp declare mapper(mmap: mt_t :: v) map(tofrom: v%a)
contains
end module fuzz_dmod
module fuzz_dfun
  use fuzz_dmod
  implicit none
contains
end module fuzz_dfun
module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 16, m = 8
  type(mt_t) :: ms
  integer :: i, j, hf2
  integer(8) :: cs
  do i = 1, n
    ms%a(i) = mod(i * 5 + 23, 101) - 50
  end do
  hf2 = 0
  !$omp target teams map(mapper(mmap), tofrom: ms) map(tofrom: hf2)
    !$omp distribute
    do i = 1, n
      if (i == 1) hf2 = merge(1, 0, omp_is_initial_device())
    end do
  !$omp end target teams
  cs = 0
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf2, 0)
end program fuzz_prog
