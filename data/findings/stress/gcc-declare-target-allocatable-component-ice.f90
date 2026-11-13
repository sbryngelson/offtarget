! # Finding (GCC 16.2, stress sweeps): a declare target module variable of a derived type with an allocatable component in a
!   target region: internal compiler error in lower_omp_target
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
!   separate memory only; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: ice: internal compiler error: in lower_omp_target
! - observed: `internal compiler error: in lower_omp_target, at omp-low.cc:13204` ("during GIMPLE pass: omplower") at the target
!   teams distribute parallel do directive, on both targets (the host compiler fails before any offload code is made)
! - expected: compiles; prints `sum= 6304` and `RESULT ran_on_host=0 check=pass`
! - rule: a variable may appear in a declare target directive in the specification part of a module ("If an extended list item is a
!   variable name, the directive must appear in the specification part of a subroutine subprogram, function subprogram, program or
!   module", 5.2 §7.8.1 p.206 l.27-28); its allocatable component is mapped by the enter data construct.
! - same-compiler control (compiles; correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5;
!   unset pass 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl)): the same program without the declare target directive
!   (controls/gcc-declare-target-allocatable-component-control.f90).
! - other families: AFAR, CCE 19/20/21 and NVHPC 25.11/26.9 run the stress programs (template.declared_alloc-omp-8/159/400-1, eight
!   allocatable components) correctly in copy mode (results/stress/s1-g5, nv1-omp). The site's finding matrix runs this file on
!   every compiler.
! - stress programs (6 cells (3 gcc_g90, 3 gcc_sm80); gate: confirmed 6; the stress kind has no confirmer path):
!   template.declared_alloc-omp-159-1, template.declared_alloc-omp-400-1, template.declared_alloc-omp-8-1
! - legality: the stress programs pass the stress gate and the pre-run check (offload.engine.prerun.check: the rules and AFAR's
!   front
!   end, two witnesses; results/parity/stress-checked); GCC is a compiler under test only and never a legality witness.
module dt_m
  implicit none
  type :: holder
    integer, allocatable :: v1(:)
  end type holder
  type(holder) :: gq
  !$omp declare target(gq)
end module dt_m

program declared_alloc_component
  use omp_lib, only: omp_is_initial_device
  use dt_m
  implicit none
  integer :: out(64), i, host_flag
  allocate(gq%v1(64))
  gq%v1 = [(3*i, i = 1, 64)]
  !$omp target enter data map(to: gq%v1)
  out = 0
  host_flag = 1
  !$omp target teams distribute parallel do map(tofrom: out, host_flag)
  do i = 1, 64
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
    out(i) = gq%v1(i) + 1
  end do
  !$omp target exit data map(delete: gq%v1)
  print '(a,i0)', 'sum= ', sum(out)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', sum(out) == 3*64*65/2 + 64)
end program declared_alloc_component
! site:
! title: declare target module variable with an allocatable component used in a target region: internal compiler error
! summary: A module variable of a derived type with an allocatable component, named in a declare target directive and read
! + in a target teams distribute parallel do loop after its component is mapped by target enter data, stops GCC 16.2 with an
! + internal compiler error (lower_omp_target) for both offload targets. Without the declare target directive the program
! + compiles and runs correctly. AFAR, CCE and NVHPC run the stress programs correctly.
! control: stress/controls/gcc-declare-target-allocatable-component-control.f90 the same program without declare target
! end site
