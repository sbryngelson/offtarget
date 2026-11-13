! # Finding: CCE 21 ftn: a target region that calls an internal
! # function which calls another internal function of the same host faults
! # on the GPU ("unspecified launch failure"; CCE 19 and 20 correct)
!
! - compilers: CCE ftn 21.0.3 and 21.0.4, -O2: this file on MI300A gfx942
!   (HSA_XNACK 0 and 1; gate confirmed); the libgomp test it comes from also
!   on MI250X gfx90a with 21.0.3.
! - expected: r= 43 44 a= 6 7 dev= T
! - actual: the kernel faults: "HSA_STATUS_ERROR_EXCEPTION: An HSAIL operation
!   resulted in a hardware exception. code: 0x1016", then "CRAY_ACC_ERROR -
!   hipStreamSynchronize returned hipErrorLaunchFailure: 'unspecified launch
!   failure'" at the target construct, exit status 1, every run.
! - rule: "If a procedure is explicitly or implicitly referenced in a target
!   construct that does not specify a device clause in which the ancestor
!   device-modifier appears then that procedure is treated as if its name had
!   appeared in an enter clause on a declare target directive" (5.2 §13.8
!   p.285 l.1-3), and a procedure referenced in such a procedure is treated
!   the same way (5.2 §7.8 p.205 l.3-6). Both rules are in 5.0 (Appendix B:
!   "implicit declare target directives for some functions ... and
!   subroutines (Fortran) were added").
! - regression: CCE 19.0.0 and 20.0.2 are correct on every form (gfx942
!   both modes; gfx90a).
! - conditions (one change each, CCE 21.0.3 and 21.0.4, gfx942 X0 and X1):
!   the fault needs the internal-to-internal call. Correct: wrap does the
!   addition itself (no call); wrap calls a module procedure instead of the
!   internal function. Faults (forms of the libgomp test): the target
!   construct in the main program or in a third internal function; with or
!   without a module procedure call next to the internal call.
! - other families: AFAR amdflang correct on this file and on the libgomp
!   test (gfx942 X0 and X1, gfx90a).
! - harvest: dev program h2-gomp-f-declare-target-3 (data/bench/harvest2; libgomp
!   testsuite libgomp.fortran/declare-target-3.f90, GPL-3.0-or-later; this
!   file is a new program, not a copy), wrong_answer on CCE 21 only, gate
!   confirmed on gfx90a.
! - legality: offload.engine.prerun.check accepts it (the rules with the race
!   rule, and the AFAR flang front end).
! CCE:  ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>;
!       module unload cray-mpich)
! Run:  OMP_TARGET_OFFLOAD=mandatory ./a.out
program p
  use omp_lib
  implicit none
  integer :: a(2), r(2)
  logical :: dev
  a = [1, 2]
  dev = .false.
  !$omp target map(tofrom: a, r) map(from: dev)
  r = wrap(a)
  dev = .not. omp_is_initial_device()
  !$omp end target
  print '(a,2(1x,i0),a,2(1x,i0),a,l1)', 'r=', r, ' a=', a, ' dev= ', dev
  if (all(r == [43, 44]) .and. all(a == [6, 7])) then
    print '(a,i0,a)', 'RESULT ran_on_host=', merge(0, 1, dev), ' check=pass'
  else
    print '(a,i0,a)', 'RESULT ran_on_host=', merge(0, 1, dev), ' check=fail'
  end if
contains
  integer function add42(y)
    integer :: y
    add42 = y + 42
  end function
  function wrap(y)
    integer :: y(2), wrap(2)
    y = y + 5
    wrap(1) = add42(y(1) - 5)
    wrap(2) = add42(y(2) - 5)
  end function
end program p
! site:
! title: ftn 21: a target region calling an internal function that calls another internal function faults on the GPU
! end site
