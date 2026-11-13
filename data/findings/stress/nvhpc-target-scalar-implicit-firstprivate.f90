! # Finding: NVHPC treats a TARGET scalar as firstprivate in a target region
!
! - compilers: NVHPC nvfortran 25.11 and 26.9, A100 (sm_80), -mp=gpu -gpu=cc80, separate
!   (-gpu=mem:separate) and managed (-gpu=mem:managed) memory, -O2
! - expected: rd= 101 s= 203 dev= 1. A scalar with the TARGET attribute referenced in a target region
!   "is treated as if it had appeared in a map clause with a map-type of tofrom" (5.2 §5.8.1 p.149
!   l.6-7; 5.0 §2.19.7 p.315 l.7-8; 6.0 §7.9.3 p.277 l.17-18), so the write s = 2*s+1 returns 203
! - actual: rd= 101 s= 101 dev= 1 on both releases and both memory modes (the region ran on the
!   device and read s; its write was not copied back: s behaves as firstprivate)
! - control (same compiler): the same program with map(tofrom: rd, dev, s)
!   (data/reports/fuzz-stress-audit/r1-target-scalar-control.f90): 203 on both releases and modes
! - other families: CCE 19/20/21 give 203 on the same program (MI300A HSA_XNACK 1 and 0; MI250X).
!   AFAR fails the same way: stress/afar-target-scalar-implicit-firstprivate.f90 (sibling entry)
! - legality: legal by reading: one initial thread in the region; rd and dev mapped tofrom, s
!   implicitly tofrom; no data race
! - evidence: results/stress/audit/runs-nvhpc.jsonl (tools/jobs/run_wingtip_fix1.sh, tools/campaigns/stress_audit.py
!   on data/reports/fuzz-stress-audit/r1-target-scalar*.f90). The confirmer gave needs_human (R22): it
!   does not draw a witness across machines; the audit counts the executed MI300A results
!   as the other-family witness for this deterministic single-construct program
program target_scalar_tofrom
  use omp_lib
  implicit none
  integer(8), target :: s
  integer(8) :: rd
  integer :: dev
  s = 101
  rd = -1
  dev = -1
  !$omp target map(tofrom: rd, dev)
    rd = s
    s = 2 * s + 1
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  print '(a,i0,a,i0,a,i0)', 'rd= ', rd, ' s= ', s, ' dev= ', dev
end program target_scalar_tofrom
! site:
! title: nvfortran -mp=gpu: scalar with the TARGET attribute is treated as firstprivate in a target region (device write lost)
! control: ../vendor/checks/src/nvhpc/control/nvhpc-target-scalar-implicit-firstprivate-control.f90 s mapped explicitly:
! + map(tofrom: rd,
! + dev, s)
! end site
