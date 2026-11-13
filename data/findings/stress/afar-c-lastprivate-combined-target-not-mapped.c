/* # Finding: AFAR amdclang drops lastprivate's implicit map on a combined
   # target construct (C)

   - compiler: AFAR amdclang 24.0.0git (drop 24.3.0), -fopenmp --offload-arch=gfx942 (MI300A, HSA_XNACK
     1 and 0) and gfx90a (MI250X, Tioga, XNACK 0), -O2
   - expected: l= 2560 dev= 1. lastprivate gives l the value of the sequentially last iteration
     (i = 64: 64 * 40) (5.2 §5.4.5), and "If the target construct is among the constituent constructs
     and the list item is not the base variable ... of a list item that appears in a map clause, the
     effect of the lastprivate clause is as if the same list item appears in a map clause with a
     map-type of tofrom" (5.2 §17.2 p.340 l.27-30; 5.0 §2.14 p.219 l.18-20)
   - actual: l= 0 dev= 1 (the region ran on the device; the final value was not copied back), on
     MI300A at XNACK 1 and 0 and on MI250X. The same with target teams distribute lastprivate(l)
     (lp-c-tdist.c).
   - XNACK 1 hang check: the audit saw this program and the other unmapped forms time out
     (rc 124 at a 60 s run limit) at XNACK 1 on tuolumne1011. It was rerun with a 600 s limit
     (tools/jobs/run_stress_fix2.sh b; results/stress/audit/runs-fix2-hang.jsonl) on tuolumne1013, 1031
     and 1011 (this program and lp-c-tdist.c), and the part-a run on 1014 had a 120 s limit. Fix
     Reran the other two forms that had timed out, target teams distribute simd and target
     parallel for (rereview-1-src/lp-tdsimd.c, lp-tpfor.c), with a 600 s limit on tuolumne1011 and 1015
     (run_stress_fix2.sh d; runs-fix3-hang.jsonl). Every run ended in seconds with l= 0 at XNACK 1
     and 0. The timeout did not reproduce, so the observed outcome is l= 0; the audit's
     timeouts are recorded as unexplained.
   - same-compiler control: the same program with map(tofrom: l)
     (data/reports/fuzz-stress-audit/r2-lastprivate-combined-control.c): 2560 on MI300A (XNACK 1 and 0,
     every node above) and MI250X. Also 2560: target teams distribute lastprivate(l) map(tofrom: l)
     and target parallel for lastprivate(l) map(tofrom: l).
     : the control passes because l is long long. With an int item the
     explicit-map form fails too (0 or a garbage value), a second AFAR defect of items smaller than
     8 bytes (afar-c-lastprivate-distribute-parallel-for-small-type.c); this finding's own form
     loses the value with int and long long alike (lp= -1 from -1, both GPUs,
     data/evidence/lead_probe/leads/lp_int_nomap.c, lp_ll_nomap.c), so it stands as stated for its long long
     program and control.
   - no other family can witness:
       CCE craycc 19/20/21 give l= 0 on this program and also on the explicit-map control
       (stress/cce-c-distribute-lastprivate-lost.c, cce-c-parallel-for-in-target.c).
       NVHPC: NVIDIA's guide documents lastprivate on distribute as unsupported (HPC Compilers
       User's Guide 25.11, §7.4, 2.9.4 "The lastprivate clause is not supported"; 2.14 "Clauses on
       combined constructs are supported to the extent that the clauses are supported on the
       component constructs"), so nvc is not expected to implement this program; it gives l= 0
       with and without the map (stress/nvhpc-c-lastprivate-teams-distribute-parallel-for-lost.c).
       Its target teams distribute lastprivate(l) gives 0 without a map and 2560 with one, but that
       clause is documented as unsupported, so it is no evidence about the C rule.
       Fix (the optional check): on target parallel for, where lastprivate is documented
       (2.9.2), nvc 25.11 and 26.9 give l= 0 without a map (rereview-1-src/lp-tpfor.c,
       runs-nvhpc-fix3.jsonl, both memory modes) and 2560 with one: nvc misses the implicit map
       there too, so it is not a witness.
     So no C front end gives the expected value for an unmapped lastprivate on a combined target
     construct. The expected value rests on the spec text, AFAR's own explicit-map control, and the
     same rule in Fortran, which AFAR flang and CCE ftn implement (r2f-lastprivate-combined.f90:
     2560).
   - legality: legal by reading: the for loop variable is private; only the lastprivate item l is
     written in the loop; dev is written by the initial thread of the second target region
   - evidence: results/stress/audit/runs.jsonl, runs-tioga.jsonl, runs-fix2.jsonl,
     runs-fix2-hang.jsonl; audit rerun: data/reports/fuzz-stress-audit/rereview-1-lp.jsonl. The
     confirmer gave needs_human (R22: the CCE cells are wrong too, so it has no witness) */
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0;
  int dev = -1;
  #pragma omp target teams distribute parallel for lastprivate(l)
  for (int i = 1; i <= 64; i++)
    l = (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", l, dev);
  return 0;
}
// site:
// title: amdclang: lastprivate on target teams distribute parallel for does not imply map(tofrom), value lost
// control: ../vendor/checks/src/afar/control/afar-c-lastprivate-combined-target-not-mapped-control.c map(tofrom: l) added
// end site
