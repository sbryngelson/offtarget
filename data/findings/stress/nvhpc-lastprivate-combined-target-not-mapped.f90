! # Finding: NVHPC drops lastprivate's implicit map on a combined target
! # construct (Fortran)
!
! - compilers: NVHPC nvfortran 25.11 and 26.9, A100 (sm_80), -mp=gpu -gpu=cc80, separate and
!   managed memory, -O2
! - expected: l= 2560 dev= 1. lastprivate gives l the value of the sequentially last iteration
!   (5.2 §5.4.5), and "If the target construct is among the constituent constructs and the list
!   item is not the base variable ... of a list item that appears in a map clause, the effect of the
!   lastprivate clause is as if the same list item appears in a map clause with a map-type of
!   tofrom" (5.2 §17.2 p.340 l.27-30; 5.0 §2.14 p.219 l.18-20)
! - actual: l= 0 dev= 1 on both releases and both memory modes
! - control (same compiler): target parallel do lastprivate(l) map(tofrom: l)
!   (data/reports/fuzz-stress-audit/r2f-lastprivate-combined-control.f90): 2560 on both releases and modes
! - other families: AFAR and CCE 19/20/21 give 2560 on this program (MI300A HSA_XNACK 1 and 0, MI250X)
! - not evidence for this finding: NVHPC also gives lp= 0 on target teams distribute
!   parallel do [simd] collapse(2) lastprivate(lp) (r7-lastprivate-collapse-{nosimd,simd}.f90), and
!   nvc gives l= 0 on the C target teams distribute lastprivate(l) (lp-c-tdist.c). Those put
!   lastprivate on distribute, which NVIDIA's guide documents as unsupported (§7.4, 2.9.4 "The
!   lastprivate clause is not supported"; 2.14 combined constructs), so they are not further cases of
!   the implicit-map defect. This program's target parallel do uses lastprivate on the worksharing
!   loop, which the guide supports (2.9.2), and is unaffected.
! - the C form (results/stress/audit/runs-nvhpc-fix3.jsonl, runs-nvhpc-fix2.jsonl): nvc
!   25.11 and 26.9 give l= 0 on target parallel for lastprivate(l)
!   (data/reports/fuzz-stress-audit/rereview-1-src/lp-tpfor.c) and 2560 with map(tofrom: l)
!   (lp-c-tpfor-map.c), both memory modes: the same missing implicit map on a documented clause
! - legality: legal by reading: the loop variable is predetermined private; only the lastprivate
!   item l is written in the loop
! - evidence: results/stress/audit/runs-nvhpc.jsonl. The confirmer gave needs_human (R22, no
!   cross-machine witness); the audit counts the MI300A results
! - coverage-parity fuzz, stratum c1 (2026-11-03): program par-c1-nvhpc-nvhpc269:1634 (target simd
!   lastprivate(lp1) with lp1 in no map clause) gives a wrong checksum on 25.11 and 26.9 (rows
!   results/parity/wingtip/results/fuzz/par-c1-nvhpc-nvhpc269/programs.jsonl; the gate confirms both
!   cells in a-d, results/parity/wingtip/results/parity/gate/fuzz/verdicts.nvhpc-topup.jsonl); with
!   map(tofrom: lp1) added it gives the expected checksum (exploration runs
!   on both releases): the missing implicit map of this finding on target simd.
!   No separate finding
program lastprivate_combined
  use omp_lib
  implicit none
  integer(8) :: l
  integer :: i, dev
  l = 0
  dev = -1
  !$omp target parallel do lastprivate(l)
  do i = 1, 64
    l = int(i, 8) * 40
  end do
  !$omp end target parallel do
  !$omp target map(tofrom: dev)
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  print '(a,i0,a,i0)', 'l= ', l, ' dev= ', dev
end program lastprivate_combined
! site:
! title: nvfortran -mp=gpu: lastprivate on target parallel do does not imply map(tofrom), final value lost
! control: ../vendor/checks/src/nvhpc/control/nvhpc-lastprivate-combined-target-not-mapped-control.f90 map(tofrom: l) added to
! + the target
! + parallel
! + do
! end site
