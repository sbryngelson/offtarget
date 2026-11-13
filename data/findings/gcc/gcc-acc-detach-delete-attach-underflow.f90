! # Finding (GCC 16.2): OpenACC exit data detach, then exit data delete: "attach count underflow"
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0,
!   NVIDIA A100 sm_80, wingtip); separate memory only; -O2; OMP_TARGET_OFFLOAD=mandatory
! - build: gfortran -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: run_error: attach count underflow
! - observed: `libgomp: attach count underflow` and exit 1 at the exit data delete, in every run on both GPUs (this file: gcc_sm80
!   and gcc_g90, 5 of 5 each with OMP_TARGET_OFFLOAD mandatory and 5 of 5 unset; results/gcc/<tc>/probes-findings.jsonl); the
!   parallel loop before it ran on the device.
! - expected: `sum= 2144`, then `RESULT ran_on_host=0 check=pass`
! - rule: in OpenACC 2.6, the version GCC documents, the delete clause performs a detach action, and "If the current device is a
!   shared memory device, or if var is not present on the device, or if the attachment counter for var for the pointer is zero, no
!   action is taken. Otherwise, the attachment counter for the pointer var is decremented" (OpenACC 2.6, section 2.7.2 "Detach
!   Action", margin lines 1115-1122; the same sentence in OpenACC 3.0, 3.2 and 3.3, the last at margin lines 1710-1711). After exit
!   data detach the attachment counter is zero, so the delete leaves it alone. OpenACC 3.4 rewords the actions with the same intent:
!   the delete clause performs a decrement counter action on the attachment counter (OpenACC 3.4 §2.7.12 l.2022-2025), "If the
!   reference counter is already zero, its value is left unchanged" (§2.7.2 l.1733-1735), and a detach pointer action at a zero
!   counter is defined (§2.7.2 l.1794-1796); the data clause errors (§2.7.3) name no attachment-counter error.
! - same-compiler control (correct: `sum= 2144`, 5 of 5 runs on each GPU): the same program without the exit data detach
!   (controls/gcc-acc{,-c}-detach-control.{f90,c}).
! - other families: CCE 19/20/21 (Fortran, MI300A and MI250X) and NVHPC 25.11/26.9 (both languages, separate and managed memory) run
!   the catalog programs acc34-clause-detach and acc34-c-clause-detach to the end (their check cannot see the detach: unobservable).
!   The site's finding matrix runs this file on every compiler.
! - gate and confirmer: 2 cells (1 gcc_g90, 1 gcc_sm80), each confirmed in the gate's four environments (a-d;
!   results/gcc/gate-tioga/ and gate-wingtip/ verdicts.jsonl); confirmer verdicts (results/gcc/confirm/batch.gcc_*.jsonl):
!   needs_human (R22-expected-weak) 2
! - catalog programs (1): acc34-clause-detach
! - legality: read against the spec (the rule above); the catalog programs of the list are legal by construction
!   (offload.engine.gen,
!   c_gen and acc_gen; no compiler). GCC is a compiler under test only and never a legality witness.
program detach_then_delete
  use openacc, only: acc_device_host, acc_on_device
  implicit none
  integer, parameter :: n = 64
  type :: holder
    integer, allocatable :: v(:)
  end type holder
  type(holder) :: h
  integer :: b(n)
  integer :: i, host_flag
  allocate(h%v(n))
  h%v = 1
  b = 0
  host_flag = 1
  !$acc enter data copyin(h)
  !$acc enter data copyin(h%v)
  !$acc parallel loop copyout(b) copy(host_flag) present(h)
  do i = 1, n
    if (i == 1) host_flag = merge(1, 0, acc_on_device(acc_device_host))
    b(i) = i + h%v(i)
  end do
  !$acc exit data detach(h%v)
  !$acc exit data delete(h%v)
  !$acc exit data delete(h)
  print '(a,i0)', 'sum= ', sum(b)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', sum(b) == 2144)
end program detach_then_delete
! site:
! title: OpenACC: exit data delete after exit data detach stops with "attach count underflow"
! summary: After exit data detach of an attached member pointer, exit data delete of its target should leave the attachment counter
! + at zero and free the data. GCC 16.2's libgomp stops the program instead with "attach count underflow" (exit 1), in Fortran and
! + C, on the MI250X and the A100; without the detach the same program runs correctly. OpenACC 2.6, the version GCC documents, says
! + a detach action at a zero attachment counter takes no action.
! control: gcc/controls/gcc-acc-detach-control.f90 the same program without the exit data detach
! end site
