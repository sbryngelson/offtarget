! # Finding (fortran-oop): SELECT TYPE with a CLASS IS guard in device code fails to link (_EXTENDS_TYPE_OF)
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy, unified), cce20 (CCE 20.0.2: copy, unified), cce21 (CCE 21.0.3: copy,
!   unified), cce21_4 (CCE 21.0.4: copy, unified); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: rejected (link_undefined_symbol, the program's own object); OMP_TARGET_OFFLOAD=mandatory
! - observed: `lld: error: undefined symbol: _EXTENDS_TYPE_OF`, every CCE release, both modes
! - expected: compiles; `r1= 121`
! - rule: Fortran 2018 11.1.11 (CLASS IS guards); no OpenMP restriction on SELECT TYPE in device procedures
! (section 6)
! - same-compiler control: TYPE IS guards only (oop-poly-select-type) link (and then take the wrong branch:
!   cce-select-type-guard-not-taken.f90)
! - other families: AFAR correct; GCC 16.2 rejects it (gcc-vtab-not-marked-for-offload.f90)
! - gate and confirmer: 8 cells, 8 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): compiler_bug (R10b-own-link-or-hang) 8
! - programs (1): oop-poly-class-is (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
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
  subroutine tag(s, t)
    !$omp declare target
    class(base_t), intent(in) :: s
    integer, intent(out) :: t
    t = 0
    select type (s)
      class is (base_t)
        t = 1
      type is (ext2)
        t = 2
    end select
  end subroutine tag
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(ext1) :: e1
  type(ext2) :: e2
  type(base_t) :: b0
  integer :: t1, t2, t3
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  !$omp target map(tofrom: e1, e2, b0) map(from: t1, t2, t3)
  call tag(e1, t1)
  call tag(e2, t2)
  call tag(b0, t3)
  !$omp end target
  r1 = 100 * t1 + 10 * t2 + t3
  ok = .true.
  ok = ok .and. (r1 == 121)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: a CLASS IS guard of SELECT TYPE in device code fails at the link
! summary: SELECT TYPE with a CLASS IS guard in a declare target subroutine called in a target region fails at the device link on
! + CCE 19, 20 and 21 (undefined _EXTENDS_TYPE_OF). AFAR runs it correctly.
! end site
! spec (requirement): the base language is Fortran 2003, 2008 and 2018, and only the few Fortran features listed in the
!   base-language section have unspecified behavior (SELECT TYPE with a CLASS IS guard is not one of them; its semantics are the
!   Fortran standard's, with no OpenMP text of its own); a declare target procedure must be executable on a device.
! "While future versions of the OpenMP specification are expected to address the following features, currently their use may
!   result in unspecified behavior." (5.2 §1.7 p.36 l.6-8)
! "Declare target directives apply to procedures and/or variables to ensure that they can be executed or accessed on a device."
!   (5.2 §7.8 p.204 l.16-17)
! spec (this program): the declare target subroutine tag uses SELECT TYPE with a CLASS IS guard and is called in a target
!   region; CCE 19, 20 and 21 build it but fail at the link (undefined symbol _EXTENDS_TYPE_OF), so the procedure cannot be
!   executed on the device.
