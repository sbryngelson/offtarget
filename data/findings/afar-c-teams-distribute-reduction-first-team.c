/* # Finding (lead 1): AFAR amdclang keeps only the first team's partial result of a
   # reduction on target teams distribute (C, -O1 and above)

   - compiler: AFAR amdclang 24.0.0git (drop 24.3.0), -fopenmp --offload-arch=gfx942 (MI300A,
     HSA_XNACK 1 and 0) and gfx90a (MI250X, Tioga, XNACK 0), -fopenmp-version=52, -O2
   - expected: l= 83200 dev= 1 (the sum of 40 * i over i = 1..64). The reduction clause applies to
     the teams leaf (5.2 §17.2 p.340 l.36-37, §5.5.8 p.134 l.18: distribute takes no reduction),
     "For each list item, a private copy is created for each implicit task or SIMD lane and is
     initialized with the initializer value of the reduction-identifier. After the end of the
     region, the original list item is updated with the values of the private copies using the
     combiner associated with the reduction-identifier" (5.2 §5.5.8 p.134 l.21-24)
   - actual: l= 40 dev= 1: the region ran on the device and the original got only the first
     team's partial sum (team 0 ran iteration 1). Every run at -O1, -O2 and -O3, MI300A at XNACK 1
     and 0 and MI250X; with 1000 iterations l= 61600 (team 0's chunk) instead of 20020000. The
     same with reduction(max: l) and the body l = max(l, i * 40) (l= 40, expected 2560; this is the
     control of the HPE packet's cce-c-distribute-lastprivate-lost report that AFAR failed,
     data/vendor/errata-for-findings.md item 23), with reduction(min: l) (l= 0, expected 40), with
     double and int items, with num_teams(64), with target followed by teams distribute, and with
     target teams reduction(+: l) around a distribute.
   - same-compiler controls (each one change): the same file at -O0 gives l= 83200;
     num_teams(8) or num_teams(4) or num_teams(1) gives 83200 (2560 for the max form);
     target teams distribute parallel for reduction(max: l) gives 2560; AFAR amdflang's
     target teams distribute reduction(max: l) over the same loop gives 2560.
   - other families: CCE craycc 19.0.0, 20.0.2, 21.0.3 and 21.0.4 give l= 83200 on this file (and
     2560, 20020000 on the max and 1000-iteration forms).
   - legality: offload.engine.rules accepts it (with the race rule and the restriction checks:
     offload.engine.prerun.check, rerun, data/evidence/lead_probe/logs/legality_new.jsonl), and nvc
     26.9 and 25.11 (NVHPC, not under test for an AFAR finding) compile it with -mp=gpu
     (data/evidence/lead_probe/logs/wingtip_witness.log); the check's other witness, the amdclang front
     end, is AFAR's own and is not counted; no gfortran or gcc is a legality witness.
     Race-free: each team updates only its private copy of l.
   - evidence: data/evidence/lead_probe/leads/ (red_*.c, red3_*.c; jobs.py, run_leads.sh), runs in
     data/evidence/lead_probe/logs/leads_*.jsonl
   - reproduction (the gate's four environments by hand: data/evidence/lead_probe/confirm_jobs.py,
     run_confirm.sh; logs/confirm_*.jsonl): MI300A, XNACK 1 and 0, (a) harness_<8 hex> and (d) a
     second run there and (b) GATE + 14 letters on tuolumne1047, (c) the path of (a) on
     tuolumne1042: l= 40 in every run (confirmed); MI250X (tioga39), (a), (b), (d): l= 40. The -O0
     and num_teams(8) controls gave 83200 in every environment; CCE 19/20/21/21.0.4 gave 83200.
   - upstream: llvm-project fixed it in 2c1650555b10 "[OpenMP][offload] Fix
     single-thread SPMD cross-team reductions (#231843)" (2026-10-14, after the AFAR drop), with the
     test offload/test/offloading/xteam_reduction_no_parallel.c; AFAR fails that test (gfx942 at
     XNACK 0 and 1, gfx90a; gate confirmed), CCE 19/20/21 and NVHPC 25.11/26.9 pass it
. */
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0;
  int dev = -1;
  #pragma omp target teams distribute reduction(+: l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l += (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", l, dev);
  return 0;
}
// site:
// title: amdclang keeps only the first team's partial result of a reduction on target teams distribute
// end site
