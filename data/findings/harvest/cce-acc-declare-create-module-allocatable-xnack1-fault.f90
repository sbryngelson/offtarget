! # Finding (known-issues harvest): CCE faults on a module allocatable in
!   declare create at HSA_XNACK=1 (MI300A)
!
! - source: MFC's compiler-ticket list (PE-53844, "CCE >17 crashes on host_data use_device for
!   module variables"), reconstructed as data/bench/harvest-known hk-008 (a declare create module
!   allocatable, host_data use_device, a deviceptr routine); the fault is at the first compute
!   construct, before host_data, so this file drops host_data
!   (data/reports/harvest-known/v008-declare-create-alloc.f90)
! - compilers: CCE 19.0.0, 20.0.2, 21.0.3, ftn -h acc -O2, MI300A at HSA_XNACK=1 (THP always)
! - expected: bad = 0, RESULT ... check=pass. For an allocatable in declare create, "for an
!   allocate statement for var ... memory will be allocated in both local memory as well as in the
!   current device memory" on a non-shared memory device (OpenACC 3.4 §2.13.2 p.83 l.3053-3057); on
!   a shared memory device the host memory is the device's; either way buf is present in the
!   parallel loop and the update copies (or leaves) the values
! - actual: CCE 19 and 20: "Memory access fault by GPU node-4 ... on address 0x6000. Reason: Write
!   access to a read-only page." (SIGABRT); CCE 21: "hipStreamSynchronize returned
!   hipErrorIllegalAddress ... from v008-declare-create-alloc.f90:19" (the parallel loop), exit 1
! - control (same compiler): HSA_XNACK=0 passes; at HSA_XNACK=1 a local allocatable made present
!   with enter data create passes (c008-local-enter-data.f90), and a fixed-size module array in
!   declare create passes (c008-fixed-module.f90), both in data/reports/harvest-known/
! - other families: NVHPC 25.11 and 26.9 (OpenACC; separate and managed memory) pass; AFAR has no
!   OpenACC
! - legality: the pre-run check (rules and the AFAR front end with -fopenacc) accepts it; present
!   requires the data present, which declare create and the allocate statement provide
! - also: hk-007 (MFC ticket OLCFHELP-19298 / HPECOE-71) and hk-013 (thornado commit 2253976852,
!   "another CCE bug") hold a module allocatable in declare create too, and fail the same way on CCE
!   19/20/21 at HSA_XNACK=1 only (19 and 20 fault, 21 hipErrorIllegalAddress; another node)
! - evidence: results/harvest-known/main (hk-007, hk-008, hk-013, CCE 19/20/21 at HSA_XNACK=1),
!   results/harvest-known/probes.tuolumne.jsonl, probes.wingtip.jsonl
module v008_m
  implicit none
  real(8), allocatable :: buf(:)
  !$acc declare create(buf)
end module v008_m

program v008
  use openacc
  use v008_m
  implicit none
  integer, parameter :: n = 4096
  integer :: i, bad, hk_host
  allocate(buf(n))
  !$acc parallel loop present(buf)
  do i = 1, n
    buf(i) = real(i, 8)
  end do
  !$acc update host(buf)
  bad = count(buf /= [(real(i, 8), i = 1, n)])
  hk_host = 1
  !$acc parallel num_gangs(1) copy(hk_host)
  if (.not. acc_on_device(acc_device_host)) hk_host = 0
  !$acc end parallel
  print '(a,i0)', 'bad = ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hk_host, ' check=', merge('pass', 'fail', bad == 0)
end program v008
! site:
! title: ftn (OpenACC): a module allocatable in declare create faults at HSA_XNACK=1
! end site
