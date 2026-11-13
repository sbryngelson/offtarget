! Minimized by compliance.fuzz_min from fuzz seed 86 (fuzz-3).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (afar) checksum=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce20
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
  ! fuzz: kernels
  !$omp target teams map(mapper(mmap), tofrom: ms) map(tofrom: hf2)
    !$omp distribute
    do i = 1, n
      if (i == 1) hf2 = merge(1, 0, omp_is_initial_device())
    end do
  !$omp end target teams
  ! fuzz: checksum
  cs = 0
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf2, 0)
end program fuzz_prog
! spec (requirement): a user-defined mapper declared with declare mapper is visible where a variable declared at the same place
!   would be, and a map clause with a mapper modifier replaces the mapping of the list item by the map clauses of the mapper.
! "The type and an optional mapper-identifier uniquely identify the mapper for use in a map clause or motion clause later in the
!   program. The visibility and accessibility of this declaration are the same as those of a variable declared at the same
!   location in the program." (5.2 §5.8.8 p.163 l.8-10)
! "The effect that a user-defined mapper has on either a map clause that maps a list item of the given base language type or a
!   motion clause that invokes the mapper and updates a list item of the given base language type is to replace the map or update
!   with a set of map clauses or updates derived from the map clauses specified by the mapper, as described in Section 5.8.3 and
!   Section 5.9." (5.2 §5.8.8 p.163 l.14-17)
! spec (this program): declare mapper(mmap: mt_t :: v) map(tofrom: v%a) in a module, used by use association in target teams
!   map(mapper(mmap), tofrom: ms) with a distribute loop, is legal; CCE 19 and 20 abort at run time (SIGABRT).
! site:
! title: ftn 19 and 20: target teams distribute with map(mapper(...)) of a use-associated declare mapper aborts (SIGABRT)
! end site
