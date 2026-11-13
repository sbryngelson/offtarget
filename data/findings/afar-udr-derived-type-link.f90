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
  !$omp target teams distribute parallel do reduction(padd: rp) map(tofrom: rp)
  do i = 1, n
    rp = pair_t(rp%x + i, rp%y + mod(i, 3))
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', rp%x * 1000 + rp%y, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang: declare reduction on a derived type used in a target loop fails at the device link (flang runtime symbols
! + undefined)
! control: ../vendor/checks/src/afar/control/afar-udr-derived-type-link-control.f90 the same reduction on a host parallel do (no
! + target
! + teams
! + distribute)
! end site
! spec (requirement): A declare reduction directive declares a user-defined reduction identifier usable in a reduction
!   clause.
! "The declare reduction directive declares a reduction-identifier that can be used in a reduction clause as a
!   user-defined reduction." (5.2 §5.5.11 p.139 l.18-19)
! spec (requirement): The identifier can be used in a reduction clause on variables of the types listed in the
!   directive, here a derived type.
! "The reduction-identifier can later be used in a reduction clause that uses variables of the types specified in the
!   declare reduction directive." (5.2 §5.5.11 p.139 l.24-26)
! spec (this program): The module declares reduction(padd: pair_t) and the program uses padd on a target teams
!   distribute parallel do; the compiler must generate the combiner and initializer for the device, and amdflang
!   instead fails at the device link on undefined flang runtime symbols.
