! # Finding (GCC 16.2, known-issues harvest): OpenACC declare create of a module allocatable: the allocate statement
!   creates no device copy ("is not mapped")
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
!   separate memory only; -O2
! - build: gfortran -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: run_error: is not mapped
! - observed: `libgomp: [0x...,4000] is not mapped` and exit 1 at the first compute construct that names the array (present(a)), in
!   every run (gcc_sm80: mandatory exit 5 of 5; unset exit 5 of 5; gcc_g90: mandatory exit 5 of 5; unset exit 5 of 5
!   (results/parity/<machine>/<tc>/probes.jsonl))
! - expected: `bad= 0`, then `RESULT ran_on_host=0 check=pass`
! - rule: in Fortran, for an allocatable in a declare create directive and a non-shared memory device, at an allocate statement
!   "memory will be allocated in both local memory as well as in the current device memory and the dynamic reference counter will be
!   set to one" (OpenACC 3.4 §2.13.2 l.3056-3057). The behaviour is OpenACC 2.6's (the changelog of OpenACC 3.4, "Changes from
!   Version 2.5 to 2.6", margin line 588: "The declare create directive with a Fortran allocatable has new behavior"), the version
!   GCC documents (libgomp.texi, "Enabling OpenACC": OpenACC 2.6).
! - same-compiler control (correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5; unset pass 5
!   of 5 (results/parity/<machine>/<tc>/probes.jsonl)): the same program with `!$acc enter data create(a)` after the allocate
!   statement (controls/gcc-acc-declare-create-allocatable-control.f90).
! - other families: CCE 19/20/21 (copy mode, MI300A and MI250X) and NVHPC 25.11/26.9 (separate and managed memory) run the harvested
!   programs correctly (hk-007, hk-013, hk-087: results/harvest-known/main*). The site's finding matrix runs this file on every
!   compiler.
! - harvested programs (6 cells (3 gcc_g90, 3 gcc_sm80); gate: confirmed 6; confirmer: needs_human (R22-expected-weak) 6): hk-007,
!   hk-013, hk-087
! - legality: the pre-run check (offload.engine.prerun.check: the rules and AFAR's front end, two witnesses) accepts the harvested
!   programs; this file is read against the rule above. GCC is a compiler under test only and never a legality witness.
module declare_create_m
  implicit none
  integer, allocatable :: a(:)
  !$acc declare create(a)
end module declare_create_m

program declare_create_allocatable
  use openacc, only: acc_device_host, acc_on_device
  use declare_create_m
  implicit none
  integer, parameter :: n = 1000
  integer :: i, bad, host_flag
  allocate(a(n))
  a = -1
  !$acc parallel loop present(a)
  do i = 1, n
    a(i) = i
  end do
  !$acc update host(a)
  bad = 0
  do i = 1, n
    if (a(i) /= i) bad = bad + 1
  end do
  host_flag = 1
  !$acc parallel num_gangs(1) copy(host_flag)
  if (.not. acc_on_device(acc_device_host)) host_flag = 0
  !$acc end parallel
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
  deallocate(a)
end program declare_create_allocatable
! site:
! title: OpenACC: declare create of a Fortran allocatable gives no device copy at the allocate statement
! summary: OpenACC 2.6 and later make an allocate statement for an allocatable in a declare create directive allocate the device
! + copy too. GCC 16.2 does not: the first compute construct that names the array stops with "is not mapped" (exit 1), on the
! + MI250X and the A100. With an explicit enter data create after the allocate statement the same program runs correctly. CCE and
! + NVHPC run the harvested programs correctly.
! control: harvest/controls/gcc-acc-declare-create-allocatable-control.f90 an enter data create after the allocate statement
! end site
