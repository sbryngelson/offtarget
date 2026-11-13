! # Finding (GCC 16.2): defaultmap(to: pointer) copies the pointer target back to the host
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0,
!   NVIDIA A100 sm_80, wingtip); separate memory only; -O2; OMP_TARGET_OFFLOAD=mandatory
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: wrong_answer
! - observed: `b(n)= 129 host wp changed: 64 shared_mem= F` and check=fail in every run on both GPUs (this file: gcc_sm80 and
!   gcc_g90, 5 of 5 each with OMP_TARGET_OFFLOAD mandatory and 5 of 5 unset; results/gcc/<tc>/probes-findings.jsonl): the region
!   runs on the device and its writes to the pointer target reach the host. The catalog program as generated
!   (tests/data/gcc_probes/dmp_repro.f90) is wrong in 10 of 10 runs on each GPU (results/gcc/<tc>/probes.jsonl).
! - expected: `b(n)= 129 host wp changed: 0 shared_mem= F` and check=pass with separate memory
! - rule: "If implicit-behavior is the name of a map type, the attribute is a data-mapping attribute determined by an implicit map
!   clause with the specified map type" (5.2 §5.8.7 p.162 l.4-5); wp is a pointer, so it is mapped as if by map(to: wp), and on exit
!   only a from or tofrom map updates the original (5.2 §5.8.3 p.154, exit step 1a). The program reads the host copy only when host
!   and device storage are separate (shared_mem= F).
! - same-compiler control (correct, 5 of 5 runs on each GPU, and the catalog form's control 10 of 10): the explicit map(to: wp) in
!   place of defaultmap(to: pointer) (controls/gcc-defaultmap-to-pointer-control.f90).
! - other families: AFAR and CCE 19/20/21 pass the catalog programs in copy mode (MI300A at HSA_XNACK=0, MI250X); NVHPC 25.11 and
!   26.9 fail them the same way (not studied here). The site's finding matrix runs this file on every compiler.
! - gate and confirmer: 6 cells (3 gcc_g90, 3 gcc_sm80), each confirmed in the gate's four environments (a-d;
!   results/gcc/gate-tioga/ and gate-wingtip/ verdicts.jsonl); confirmer verdicts (results/gcc/confirm/batch.gcc_*.jsonl):
!   needs_human (R22-expected-weak) 6
! - catalog programs (3): omp50-clause-defaultmap-pointer, omp52-clause-defaultmap-pointer, omp60-clause-defaultmap-pointer
! - legality: read against the spec (the rule above); the catalog programs of the list are legal by construction
!   (offload.engine.gen,
!   c_gen and acc_gen; no compiler). GCC is a compiler under test only and never a legality witness.
program defaultmap_to_pointer
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, pointer :: wp(:)
  integer :: b(n), zc(1)
  integer :: i, host_flag, changed
  logical :: shared_mem
  allocate(wp(n))
  wp = 0
  b = 0
  host_flag = 1
  zc = 0
  ! separate memory? (a write to a map(to:) array is visible on the host only when storage is shared)
  !$omp target map(to: zc)
    zc(1) = 1
  !$omp end target
  shared_mem = zc(1) == 1
  !$omp target map(from: b) map(tofrom: host_flag) defaultmap(to: pointer)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      wp(i) = 2*i
      b(i) = wp(i) + 1
    end do
  !$omp end target
  changed = count(wp /= 0)
  print '(a,i0,a,i0,a,l1)', 'b(n)= ', b(n), ' host wp changed: ', changed, ' shared_mem= ', shared_mem
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', &
    merge('pass', 'fail', b(n) == 2*n + 1 .and. (shared_mem .or. changed == 0))
  deallocate(wp)
end program defaultmap_to_pointer
! site:
! title: defaultmap(to: pointer) on a target region copies the pointer target back to the host
! summary: A Fortran pointer referenced in a target region with defaultmap(to: pointer) should be mapped as if by map(to:): the
! + device's writes to its target stay on the device. GCC 16.2 copies them back to the host (64 of 64 elements changed) on the
! + MI250X and the A100 with separate memory. The same region with an explicit map(to: wp) leaves the host copy unchanged. NVHPC
! + 25.11 and 26.9 behave the same way on this program (not studied further); AFAR and CCE leave the host copy unchanged.
! control: gcc/controls/gcc-defaultmap-to-pointer-control.f90 map(to: wp) in place of defaultmap(to: pointer)
! end site
