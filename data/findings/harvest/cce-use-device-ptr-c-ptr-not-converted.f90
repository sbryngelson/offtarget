! # Finding (known-issues harvest): CCE does not convert a C_PTR list item of
!   use_device_ptr: the region sees the host address
!
! - source: the NVIDIA forum topic 290317 (nvfortran dropping use_device_addr on an allocatable,
!   TPR 36867) gave data/bench/harvest-known hk-040, which compares the use_device_addr address of an
!   allocatable with the use_device_ptr address of a C_PTR to it; this file is the use_device_ptr
!   half (data/reports/harvest-known/v040-ptr-print.f90)
! - compilers: CCE 19.0.0, 20.0.2, 21.0.3 (ftn -fopenmp), copy mode: gfx90a (Tioga, HSA_XNACK=0)
!   and gfx942 at HSA_XNACK=0 (MI300A); at HSA_XNACK=1 on MI300A the mapped address is the host
!   address, so the missing conversion is not visible (check=pass)
! - expected: seen equals mapped (the device address of tab), RESULT ... check=pass
! - actual: seen equals host: e.g. CCE 19 "host 48BEC0 mapped 155544200000 seen 48BEC0", the same
!   on 20 and 21; RESULT ... check=fail. A device kernel given this pointer would read host memory.
!   The observation does not rest on omp_get_mapped_ptr (a routine of the compiler under test):
!   in copy mode device memory is separate, so seen = the host address is wrong whatever it returns
! - control (same compiler): use_device_addr(tab) on the allocatable itself gives the mapped
!   address (data/reports/harvest-known/v040-addr.f90, check=pass on CCE 19/20/21)
! - other families: AFAR converts it (seen = mapped); NVHPC 25.11 and 26.9 abort at the construct
!   (harvest/nvhpc-use-device-ptr-c-ptr-not-found.f90)
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
! - evidence: results/harvest-known/main.tioga (hk-040, gate: confirmed); the MI250X probe runs' output
!   (results/harvest-known/logs/tioga/probe.f656gDkdAd9R.log and probe.f656k2mjQdoD.log; their rows file
!   probes.tioga.jsonl was not kept); results/harvest-known/probes.tuolumne.jsonl (MI300A, v040-ptr.f90:
!   fail at HSA_XNACK=0, pass at 1)
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
! title: use_device_ptr does not convert a C_PTR list item: the region sees the host address
! end site
