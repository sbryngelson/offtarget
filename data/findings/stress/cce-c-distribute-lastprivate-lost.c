/* # Finding: CCE craycc loses lastprivate on a distribute construct in a
   # target region, even with an explicit map (C)

   - compilers: CCE craycc 19.0.0, 20.0.2, 21.0.3, MI300A (gfx942), HSA_XNACK 1 and 0, -O2
   - expected: l= 2560 dev= 1. lastprivate on distribute gives the original l the value of the
     sequentially last iteration (i = 64: 64 * 40) (5.2 §5.4.5; §11.6 distribute accepts
     lastprivate); map(tofrom: l) on the target leaf (§17.2 p.340 l.21-30 applies lastprivate to
     the distribute leaf and map to the target leaf) brings it back
   - actual: l= 0 dev= 1 on all three releases and both XNACK settings, in both forms:
       this file               target teams distribute lastprivate(l) map(tofrom: l)
       lp-c-tdist-split.c      target map(tofrom: l, dev) { teams distribute lastprivate(l) }
     (data/reports/fuzz-stress-audit/; the audit saw the first form fail on CCE 19 and 21)
   - in-program control (lp-c-tdist-split.c): dev is mapped tofrom in the same map clause as l and
     written inside the same distribute loop (at i = 1); it comes back as 1 while l comes back as 0,
     which rules out "a scalar map in a distribute region" as the cause
   - same-compiler control: lp-c-tdist-copy.c, the same target teams distribute loop without
     lastprivate, where the last iteration stores its value in a mapped array: l= 2560 on CCE
     19/20/21, both XNACK settings. A reduction(max: l) on target teams distribute parallel for
     (lp-c-tdpf-red.c) gives 2560 too
   - other families: AFAR amdclang (both forms, both XNACK settings) and NVHPC nvc 25.11 / 26.9
     (A100, separate and managed) give 2560 on both forms
   - not the known finding: cce-c-parallel-for-in-target.c covers lastprivate on a parallel for
     nested in a target region (CCE also gives 0 on target parallel for lastprivate(l)
     map(tofrom: l), lp-c-tpfor-map.c, which that finding explains). This program has no parallel
     for: the loss is on distribute. On target teams distribute parallel for (candidate 2b,
     r2-lastprivate-combined-control.c) both leaves carry lastprivate, so both defects apply
   - legality: legal by reading: the loop variable is private; only the lastprivate item l is
     written in the loop; dev is written by the initial thread of the second target region. The
     explicit map is legal: 5.2 §13.8 p.286 l.29-30 restricts only data-sharing clauses applied to
     the target leaf, and the 5.0 §2.19.7.1 restriction (p.321 l.25-26) exempts combined constructs
   - evidence: results/stress/audit/runs-fix2.jsonl (tools/jobs/run_stress_fix2.sh a) and
     runs-nvhpc-fix2.jsonl (tools/jobs/run_wingtip_fix2.sh); the confirmer was not run on it
   - build: craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa -Xopenmp-target=amdgcn-amd-amdhsa
     -march=gfx942 -O2 (offload/engine/toolchains.py C_FLAGS); the program is the audit file as run
     (out[] is unused here) */
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0, out[1] = {0};
  int dev = -1;
  #pragma omp target teams distribute lastprivate(l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l = (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", l, dev);
  return 0;
}
// site:
// title: craycc/ftn: lastprivate on distribute in a target region loses the final value, even with an explicit map
// control: ../vendor/checks/src/cce/control/cce-c-distribute-lastprivate-lost-control.c reduction(max: l) instead of lastprivate(l)
// end site
