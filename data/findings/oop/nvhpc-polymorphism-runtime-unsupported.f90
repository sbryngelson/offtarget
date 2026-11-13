! # Finding (fortran-oop): SELECT TYPE, CLASS(*) and finalization in device code: 'runtime function not supported'
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11: managed, separate), nvhpc269 (NVHPC 26.9: managed, separate); -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -O2 (managed: -gpu=mem:managed)
! - failure: rejected (not_implemented); OMP_TARGET_OFFLOAD=mandatory
! - observed: `NVFORTRAN-S-1058-Call to Compiler runtime function not supported - pgf90_same_type_as_i8` (SELECT TYPE),
!   `pgf90_init_unl_poly_desc_i8` (CLASS(*)), `pgf90_finalize_i8` (finalization), NVHPC 25.11 and 26.9, both modes.
!   oop-assignfinal-final-dealloc fails on the ALLOCATE instead (`pgf90_calloc04a_i8`): not counted here. The claim rests on
!   NVHPC's own messages; its user guide does not mention these features in device code
! - expected: compiles; `r1= 10 r2= 100 r3= -1`
! - rule: Fortran 2018 11.1.11, 7.5.6.3; no OpenMP restriction (section 6)
! - other families: AFAR correct on all six; CCE takes the wrong SELECT TYPE branch (cce-select-type-guard-not-taken.f90); GCC
!   rejects SELECT TYPE (gcc-vtab-not-marked-for-offload.f90)
! - gate and confirmer: 24 cells, 24 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): unsupported (R05-unsupported) 24
! - programs (6): oop-poly-select-type, oop-poly-class-is, oop-unlimited-select-type, oop-unlimited-classify,
!   oop-assignfinal-final-local, oop-assignfinal-final-assign (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the nvhpc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and a CCE compile (tools/campaigns/oop.py legality,
!   results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type base_t
    integer :: a = 0
  end type base_t
  type, extends(base_t) :: ext1
    integer :: u = 0
  end type ext1
  type, extends(base_t) :: ext2
    integer :: v = 0
  end type ext2
contains
  subroutine bump(s)
    !$omp declare target
    class(base_t), intent(inout) :: s
    select type (s)
      type is (ext1)
        s%u = s%u + 10
      type is (ext2)
        s%v = s%v + 100
      class default
        s%a = -1
    end select
  end subroutine bump
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2, r3
  type(ext1) :: e1
  type(ext2) :: e2
  type(base_t) :: b0
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  !$omp target map(tofrom: e1, e2, b0)
  call bump(e1)
  call bump(e2)
  call bump(b0)
  !$omp end target
  r1 = e1%u
  r2 = e2%v
  r3 = b0%a
  ok = .true.
  ok = ok .and. (r1 == 10)
  ok = ok .and. (r2 == 100)
  ok = ok .and. (r3 == -1)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0)', 'r3= ', r3
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: SELECT TYPE, CLASS(*) and finalization are not supported in device code
! summary: SELECT TYPE on a CLASS dummy, a CLASS(*) dummy and the finalization of a local object in declare target procedures are
! + rejected by NVHPC 25.11 and 26.9: the compiler reports the runtime routines they need as not supported on the device (NVHPC's
! + own message; its guide does not mention these features). AFAR runs all six programs correctly.
! end site
! spec (requirement): the base language is Fortran 2003, 2008 and 2018 with only a short list of features of unspecified
!   behavior (SELECT TYPE, CLASS(*) and finalization are not on it; their semantics are the Fortran standard's, with no OpenMP
!   text of their own), and a declare target procedure must be executable on a device.
! "While future versions of the OpenMP specification are expected to address the following features, currently their use may
!   result in unspecified behavior." (5.2 §1.7 p.36 l.6-8)
! "Declare target directives apply to procedures and/or variables to ensure that they can be executed or accessed on a device."
!   (5.2 §7.8 p.204 l.16-17)
! spec (this program): bump is a declare target subroutine with a CLASS dummy and SELECT TYPE called in a target region; NVHPC
!   rejects it with 'Call to Compiler runtime function not supported - pgf90_same_type_as_i8', so the procedure cannot be executed
!   on the device. The same message appears for CLASS(*) and for finalization of a local object.
