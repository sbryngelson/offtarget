! # Finding (fortran-oop): SELECT TYPE on a CLASS dummy in device code: '__vtab_... referenced in offloaded code but not marked'
!
! - toolchains and modes that fail: gcc_g90 (GCC 16.2 (gfx90a): copy), gcc_sm80 (GCC 16.2 (sm_80): copy); -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic (gcc_sm80)
! - failure: rejected (diagnostic); OMP_TARGET_OFFLOAD=mandatory
! - observed: `error: variable '__vtab_oop_m_Ext1' has been referenced in offloaded code but hasn't been marked to be included in
!   the offloaded code` (the compiler's own type descriptor)
! - expected: compiles; `r1= 10 r2= 100 r3= -1`
! - rule: Fortran 2018 11.1.11; the program cannot name a compiler-generated vtable in a declare target directive (it has no
!   Fortran name), and every procedure it accesses is declare target
! - other families: AFAR correct; CCE takes the wrong guard (cce-select-type-guard-not-taken.f90)
! - gate and confirmer: 10 cells, 10 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): compiler_bug (R11-compile-rejection) 5, needs_human (R12b-compile-undecided) 5
! - programs (5): oop-poly-select-type, oop-poly-class-is, oop-poly-pointer, oop-unlimited-select-type, oop-unlimited-classify
!   (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the gcc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and a CCE compile and NVHPC 26.9 nvfortran (compile only) (tools/campaigns/oop.py legality,
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
! title: SELECT TYPE in a device procedure is rejected: the type's vtable is not offloaded
! summary: A declare target subroutine with a CLASS dummy and SELECT TYPE, called in a target region, is rejected by GCC 16.2: the
! + compiler-generated type descriptor (__vtab_...) is referenced in offloaded code but not marked for offloading. The program
! + cannot name that variable. AFAR runs the program correctly.
! end site
! spec (requirement): the base language is Fortran 2003, 2008 and 2018 with only a short list of features of unspecified
!   behavior (SELECT TYPE is not on it; its semantics are the Fortran standard's, with no OpenMP text of its own), and a variable
!   with static storage duration declared in a device routine is treated as if it appeared in an enter clause of a declare target
!   directive. No text covers compiler-generated type descriptors; the nearest rule is this implicit declare target rule.
! "While future versions of the OpenMP specification are expected to address the following features, currently their use may
!   result in unspecified behavior." (5.2 §1.7 p.36 l.6-8)
! "If a variable with static storage duration is declared in a device routine then the named variable is treated as if it had
!   appeared in an enter clause on a declare target directive." (5.2 §7.8 p.204 l.25-26)
! spec (this program): bump is a declare target subroutine with a CLASS dummy and SELECT TYPE; the compiler's own type
!   descriptor (__vtab_...), which has no Fortran name and cannot appear in a declare target directive, is a static variable the
!   device routine needs, and GCC 16.2 rejects the program because that variable is not marked for offloading.
