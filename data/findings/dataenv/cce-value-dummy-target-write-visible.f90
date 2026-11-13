! # Finding: at -O2, CCE ftn 19/20/21 make a target region's write to a VALUE dummy
! # visible to the host (no transfer of the dummy; it is firstprivate in the region)
!
! - compilers: CCE ftn 19.0.0, 20.0.2, 21.0.3 (MI300A gfx942), -O2 and -O3, HSA_XNACK 0 and 1
! - expected: rd= 5 vout= 101 dev= 1
! - actual: rd= 5 vout= 203 dev= 1 (every run: 3 repeats per cell, CCE 19/20/21 x XNACK 0/1 x -O2/-O3)
! - rule: v is a scalar dummy with the VALUE attribute, without the TARGET, ALLOCATABLE or POINTER attribute,
!   in no clause of the target construct, so it is not mapped: "If the above rules do not apply then a
!   scalar variable is not mapped but instead has an implicit data-sharing attribute of firstprivate"
!   (OpenMP 5.2 §5.8.1 p.149 l.8-9; 5.0 §2.19.7 p.315 l.9-10; 6.0 §7.9.3 p.277 l.22-23), and "In a target
!   construct, variables that are not mapped after applying data-mapping attribute rules (see Section 5.8)
!   are firstprivate" (5.2 §5.1.1 p.99 l.19-20). The region's v = 2*v + 1 writes its private copy, so the
!   procedure's v is still 101 after the region and vout = v returns 101. (A VALUE scalar is Fortran 2003;
!   OpenMP 5.0 §1.7 lists only the Fortran 2008 extension of VALUE as unspecified.)
! - what happens (not a map and not a copy-back): with CRAY_ACC_DEBUG=2 (CCE 19, HSA_XNACK 0) the -O2 build
!   of results/dataenv/probe_fr1/vd_write.f90 (this program without its header and its dev region)
!   launches `p_$ck_L23_3` from the call site at its line 23 (sub is inlined into the main program) and
!   transfers only `r` ("allocate 'r'", then "copy to host, free 'r'"); nothing of v is transferred, yet
!   the host reads 203. The -O0 build launches `sub_$ck_L6_1`, transfers the same `r`, and the host reads
!   101.
!   (trace: results/dataenv/probe_fr1/trace.out; review, section 5)
! - conditions (each a one-change variant, CCE 19/20/21, HSA_XNACK 0 and 1, results/dataenv/probe_fr1/):
!   - correct at -O0 and -O1; wrong at -O2 and -O3;
!   - correct when the region only reads v (r = v);
!   - correct when the region also calls omp_is_initial_device();
!   - wrong with sub a module procedure too (the generator's form, the trial's 9 CCE cells, gfx942 and
!     gfx90a, both modes: results/dataenv/pilot_all/).
! - same-compiler controls (all correct, -O2): firstprivate(v) on the target construct; v a by-reference
!   intent(inout) dummy instead of VALUE; a local copy u = v written in the region instead of v.
! - other families: AFAR amdflang 24.0.0git (drop 24.3.0) correct on this file at -O0 to -O3, both modes;
!   NVHPC 25.11 and 26.9 (A100, separate and managed) correct on the generator's module-procedure form
!   (the trial's rows); this file was not run on NVHPC.
! - legality: offload.engine.prerun.check accepts it (offload.engine.rules with the race rule, and the AFAR flang
!   front end); the region is executed by one initial thread; no compiler under test, gfortran or gcc is a
!   legality witness.
! - found by: the data-environment pilot, rule omp-target-value-dummy-firstprivate
!   (catalog/dataenv_rules.yaml); gate verdict confirmed on all 9 CCE cells.
!   This 22-line reproducer is the reviewer's.
! CCE:  ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; module unload cray-mpich)
! AFAR: amdflang -fopenmp --offload-arch=gfx942 -O2
! Run:  OMP_TARGET_OFFLOAD=mandatory ./a.out
subroutine sub(v, rd, vout)
  integer, value :: v
  integer, intent(out) :: rd, vout
  integer :: r
  r = -1
  !$omp target map(from: r)
    v = 2*v + 1
    r = 5
  !$omp end target
  rd = r
  vout = v          ! CCE 19/20/21 -O2: 203; expected 101
end subroutine sub

program value_dummy_target_write
  use omp_lib, only: omp_is_initial_device
  implicit none
  interface
    subroutine sub(v, rd, vout)
      integer, value :: v
      integer, intent(out) :: rd, vout
    end subroutine sub
  end interface
  integer :: rd, vout, dev
  dev = -1
  !$omp target map(from: dev)
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  call sub(101, rd, vout)
  print '(a,i0,a,i0,a,i0)', 'rd= ', rd, ' vout= ', vout, ' dev= ', dev
end program value_dummy_target_write
! site:
! title: ftn at -O2: a target region's write to a VALUE dummy, firstprivate there, becomes visible to the host
! end site
