! # Finding (known-issues harvest): NVHPC aborts on use_device_ptr of a C_PTR
!   that points to mapped data ("data in use_device clause was not found")
!
! - source: the NVIDIA forum topic 290317 (nvfortran dropping use_device_addr on an allocatable,
!   TPR 36867; that defect is gone in 25.11 and 26.9) gave data/bench/harvest-known hk-040; this file is
!   its use_device_ptr half (data/reports/harvest-known/v040-ptr-print.f90)
! - compilers: NVHPC nvfortran 25.11 and 26.9, -mp=gpu -gpu=cc80 (separate and managed memory)
! - expected: seen equals mapped (the device address of tab), RESULT ... check=pass
! - actual: the run stops at the target data construct, exit status 1: "FATAL ERROR: data in
!   use_device clause was not found on device 1: host:0x4197a8", a static address (cp's own
!   storage; tab is on the heap, the present table lists it at host:0x1f173160), both releases,
!   both memory modes, with and without OMP_TARGET_OFFLOAD=mandatory. The compiler also warns
!   "Use of the USE_DEVICE_PTR clause is deprecated" for this C_PTR list item
! - control (same compiler): use_device_addr(tab) on the allocatable gives the mapped address
!   (data/reports/harvest-known/v040-addr.f90, check=pass); the C form, use_device_ptr of a C
!   pointer, converts correctly (data/reports/harvest-known/c018-data-if-true.c)
! - other families: AFAR converts it (seen = mapped); CCE 19/20/21 leave the host address
!   (harvest/cce-use-device-ptr-c-ptr-not-converted.f90)
!   This file uses omp_get_mapped_ptr as the reference: AFAR at HSA_XNACK=1 (MI300A) returns a
!   null pointer for it, the known defect of afar-xnack1-target-is-present.f90 (nothing is
!   recorded present in unified memory), so that cell fails for another reason
! - legality: "If a list item that appears in a use_device_ptr clause is of type C_PTR and
!   points to a data entity that is mapped to the device data environment, references to the list
!   item in the structured block ... are converted into references to a device pointer that is
!   local to the structured block and that refers to the device address of the corresponding
!   entity" (OpenMP 5.2 §5.4.8 p.122 l.1-5); tab is mapped by target enter data and cp =
!   c_loc(tab); the C_PTR form is the one 5.2 keeps (the non-C_PTR form is deprecated, l.8-10).
!   omp_get_mapped_ptr is OpenMP 5.1 (§3.8.11); the pre-run check accepts the program
! - evidence: results/harvest-known/main.wingtip (hk-040, gate: confirmed), results/harvest-known/probes.wingtip.jsonl
program v040pp
  use iso_c_binding
  use omp_lib
  implicit none
  integer, parameter :: n = 1024
  integer, allocatable, target :: tab(:)
  type(c_ptr), target :: cp
  type(c_ptr) :: p_ptr, p_map
  integer :: hk_host
  allocate(tab(n))
  tab = 7
  !$omp target enter data map(to: tab)
  p_map = omp_get_mapped_ptr(c_loc(tab), omp_get_default_device())
  cp = c_loc(tab)
  !$omp target data use_device_ptr(cp)
  p_ptr = cp
  !$omp end target data
  !$omp target exit data map(delete: tab)
  print '(a,z0)', 'host   ', transfer(c_loc(tab), 0_c_intptr_t)
  print '(a,z0)', 'mapped ', transfer(p_map, 0_c_intptr_t)
  print '(a,z0)', 'seen   ', transfer(p_ptr, 0_c_intptr_t)
  print '(a,z0)', 'loc(cp) ', transfer(c_loc(cp), 0_c_intptr_t)
  hk_host = 1
  !$omp target map(tofrom: hk_host)
  if (.not. omp_is_initial_device()) hk_host = 0
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hk_host, ' check=', merge('pass', 'fail', c_associated(p_ptr, p_map))
end program v040pp
! site:
! title: nvfortran aborts on use_device_ptr of a C_PTR to mapped data ("data in use_device clause was not found")
! end site
