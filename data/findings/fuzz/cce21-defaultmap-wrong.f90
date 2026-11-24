! # Finding (leads): CCE 21 gives a wrong result on a Fortran OpenMP program with a defaultmap clause
!
! - toolchains and modes that fail: cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes: unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: wrong_answer (check=fail)
! - observed: `checksum= 1` with `check=fail`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `checksum= 1048575` with `check=pass`
! - rule: a conforming program's result is the one its constructs define: "The defaultmap clause determines the implicit
!   data-mapping or data-sharing attribute of certain variables that are referenced in a target construct, in accordance with the
!   rules given in Section 5.8.1." (OpenMP 5.2 §5.8.7 p.161 l.14-16)
! - same-compiler control: controls/lead-g1x0-o3-1784-cce21-delete-clause-defaultmap-to-scalar-control.f90 (one change from this
!   file; correct on cce21 (CCE 21.0.3); rows results/leads/reduce/lead-g1x0-o3-1784-cce21/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2) run the file correctly (site
!   rows, check case site-fuzz--cce21-defaultmap-wrong); gcc (GCC 16.2.0) fail it another way, e.g. `Program received signal
!   SIGSEGV: Segmentation fault - invalid memory reference.` (killed by signal 11)
! - programs (3): g1x0-o3:654, g1x0-o3:585, g1x0-o3:1784
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce19, cce20 run it correctly in the
!   confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
! - releases: CCE 19.0.0 and 20.0.2 run it correctly; CCE 21.0.3 and 21.0.4 fail it the same way
integer function ge1(x)
  implicit none
  integer, intent(in) :: x
  !$omp declare target
  ge1 = 0
end function ge1
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 16, m = 2
  type :: nd_t
    integer :: k(n)
  end type nd_t
  type :: rec_t
    integer, pointer :: pc(:)
    type(nd_t) :: nd
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer :: i, j, r1a, hf1
  integer(8) :: cs
  do i = 1, n
    dr%nd%k(i) = mod(i * 31 + 27, 211) - 105
  end do
  r1a = 1
  hf1 = 0
  ! fuzz: kernels
  !$omp target map(always, to: dr%pc) map(to: dr%nd%k) map(tofrom: hf1) map(tofrom: r1a) &
  !$omp& defaultmap(to: scalar)
    hf1 = merge(1, 0, omp_is_initial_device())
    do i = n, 1, -1
      r1a = ior(r1a, 1048575)
    end do
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == 1048575_8)
end program fuzz_prog

! site:
! title: CCE: wrong with defaultmap
! summary: CCE 21 gives a wrong result on a Fortran OpenMP program with a defaultmap clause.
! control: fuzz/controls/lead-g1x0-o3-1784-cce21-delete-clause-defaultmap-to-scalar-control.f90 one change from the finding; correct
! + on cce21
! end site
