/* # Finding: NVHPC accepts lastprivate on target teams distribute
   # parallel for, which its guide documents as unsupported, and gives a wrong answer (C)

   - class: an unsupported clause accepted silently with a wrong answer, the R6
     report-candidate class (as nvhpc-depend-inoutset-ignored.f90); a support claim it contradicts
     is partial_support (data/reports/rulings.md, documented limitations), not a compiler bug in a
     documented feature. NVIDIA HPC Compilers User's Guide 25.11 (and 26.9), §7.4 OpenMP Subset:
       2.9.4 Distribute Directives: "The lastprivate clause is not supported"
       2.14 Clauses on Combined and Composite Constructs: "Clauses on combined constructs are
       supported to the extent that the clauses are supported on the component constructs."
     On this construct lastprivate applies to the distribute and for leaves (5.2 §17.2), so it is
     not supported here. nvc gives no diagnostic. The claim is catalog/omp/claims.yaml
     onleaf.distribute.lastprivate (the triage reads it).
   - compilers: NVHPC nvc 25.11 and 26.9, A100 (sm_80), -mp=gpu -gpu=cc80, separate and managed
     memory, -O2
   - expected: l= 2560 dev= 1. lastprivate gives the original l the value of the sequentially last
     iteration (i = 64: 64 * 40) (5.2 §5.4.5; §17.2 p.340 l.21-30 applies it to the distribute and
     for leaves), and map(tofrom: l) on the target leaf brings it back to the host. The explicit
     map is legal: 5.2 §13.8 p.286 l.29-30 restricts only data-sharing clauses applied to the target
     leaf, and the 5.0 §2.19.7.1 restriction (p.321 l.25-26) exempts combined constructs
   - actual: l= 0 dev= 1, both releases, both memory modes
   - same-compiler controls, all l= 2560 on both releases and modes
     (data/reports/fuzz-stress-audit/, runs in results/stress/audit/runs-nvhpc-fix2.jsonl):
       lp-c-tdpf-red.c   the same construct and loop with reduction(max: l) instead of lastprivate
       lp-c-tdpf-copy.c  the same construct, private(l), the last iteration stores l in a mapped array
       lp-c-tdist-map.c  target teams distribute lastprivate(l) map(tofrom: l) (no parallel for)
       lp-c-tpfor-map.c  target parallel for lastprivate(l) map(tofrom: l) (no teams distribute)
       lp-c-tdist-split.c target map(tofrom: l) around teams distribute lastprivate(l)
     The worksharing-loop form (lp-c-tpfor-map.c) uses a documented clause ("The lastprivate clause
     is supported", 2.9.2) and gives 2560. The distribute-only forms (lp-c-tdist-map.c,
     lp-c-tdist-split.c) also give 2560, but that is undocumented behaviour: the guide says
     lastprivate on distribute is not supported. So the composite gives a wrong answer for a clause
     the guide excludes; the controls show that the value can be returned, not that nvc supports it.
   - other families: AFAR amdclang gives 2560 on this program (MI300A HSA_XNACK 1 and 0, MI250X).
     CCE craycc gives 0 here too (see data/reports/fuzz-stress.md, candidate 2b).
   - related, not the same: nvhpc-c-parallel-for-firstprivate-in-target.c is a compile failure
     ("Failed to translate OpenMP region") of a parallel for nested in a target region; this program
     compiles and runs a combined construct. Without the map (r2-lastprivate-combined.c and
     lp-c-tdist.c) nvc also gives 0: the missing implicit map, the C form of
     stress/nvhpc-lastprivate-combined-target-not-mapped.f90.
   - legality: legal by reading: the for loop variable is private; only the lastprivate item l is
     written in the loop; dev is written by the initial thread of the second target region
   - evidence: tools/jobs/run_wingtip_fix2.sh (tools/campaigns/stress_audit.py); the confirmer was not run on it */
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0;
  int dev = -1;
  #pragma omp target teams distribute parallel for lastprivate(l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l = (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", l, dev);
  return 0;
}
// site:
// title: nvc -mp=gpu: lastprivate on target teams distribute parallel for accepted silently, value lost
// control: ../vendor/checks/src/nvhpc/control/nvhpc-c-lastprivate-teams-distribute-parallel-for-lost-control.c reduction(max: l)
// + instead of
// + lastprivate(l)
// end site
