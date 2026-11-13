! # Finding: NVHPC loses the device write to a declare target scalar
!
! - compilers: NVHPC nvfortran 25.11 and 26.9, A100 (sm_80), -mp=gpu -gpu=cc80, separate and
!   managed memory, -O2
! - expected: g= 203 dev= 1. g appears in an enter clause (the 5.0 declare target(list) form). A
!   variable in an enter clause referenced in a target construct is treated as map(tofrom) (5.2
!   §5.8.1 p.148 l.9-11); its corresponding list item is never removed, "as if its reference count
!   was initialized to positive infinity" (§5.8.4 p.159 l.10-14), so on entry and exit there is no
!   transfer (§5.8.3 p.153 l.1-17, p.153 l.31-35, p.154 l.1-11): the region reads the device copy set by
!   "target update to" (101), writes 203 to it, and "target update from" returns 203
! - actual: g= 101 dev= 1 on both releases and both memory modes
! - control (same compiler): the same program with an explicit map(tofrom: dev, g)
!   (data/reports/fuzz-stress-audit/r4-declare-target-scalar-control.f90): 203 on both releases and
!   modes. (CCE 21 fails that control: stress/cce21-declare-target-scalar-map-write-lost.f90.)
! - other families: AFAR and CCE 19/20/21 give 203 on this program (MI300A HSA_XNACK 1 and 0)
! - legality: legal by reading: a module variable, no parallelism in the region
! - evidence: results/stress/audit/runs-nvhpc.jsonl (tools/jobs/run_wingtip_fix1.sh). The confirmer gave
!   needs_human (R22, no cross-machine witness); the audit counts the MI300A results
module dt_scalar_m
  implicit none
  integer(8) :: g
  !$omp declare target(g)
end module dt_scalar_m
program declare_target_scalar
  use omp_lib
  use dt_scalar_m
  implicit none
  integer :: dev
  g = 101
  dev = -1
  !$omp target update to(g)
  !$omp target map(tofrom: dev)
    g = 2 * g + 1
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  !$omp target update from(g)
  print '(a,i0,a,i0)', 'g= ', g, ' dev= ', dev
end program declare_target_scalar
! site:
! title: nvfortran -mp=gpu: write to a declare target module scalar in a target region is lost (implicit map)
! control: ../vendor/checks/src/nvhpc/control/nvhpc-declare-target-scalar-write-lost-control.f90 g mapped explicitly: map(tofrom:
! + dev, g)
! end site
