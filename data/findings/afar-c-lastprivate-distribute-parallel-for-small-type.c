/* # Finding (lead 2): AFAR amdclang returns 0 or a garbage value for a lastprivate item
   # of fewer than 8 bytes on target teams distribute parallel for (C)

   - compiler: AFAR amdclang 24.0.0git (drop 24.3.0), -fopenmp --offload-arch=gfx942 (MI300A,
     HSA_XNACK 1 and 0) and gfx90a (MI250X, Tioga, XNACK 0), -fopenmp-version=52, -O2 and -O0
   - expected: lp= 192 dev= 1. lastprivate gives the original lp the value of the sequentially
     last iteration (i = 64: 3 * 64): "the value of each new list item from the sequentially last
     iteration of the associated loops ... is assigned to the original list item" (5.2 §5.4.5
     p.115 l.12-16); on the combined construct it applies to the distribute and for leaves (5.2
     §17.2 p.340 l.21-22) and map(tofrom: lp) on the target leaf brings the value to the host.
   - actual: MI300A (XNACK 1 and 0, -O2 and -O0): lp= 0 or a value that varies from run to run
     (-1191462675, 948123843, 16246, ...; the trial saw 104571, 82972, 165175, 151912, 17038;
     the review's 12 runs all printed 0);
     MI250X: lp= 0 in every run. The same with short (14674, -18864, ...) and float (-1.1e-05, ...);
     with target followed by teams distribute parallel for lastprivate(lp) inside it.
   - same-compiler controls (each one change): long long lp or double lp gives 192 in every run
     on both GPUs; target teams distribute lastprivate(lp) map(tofrom: lp) with the int gives 192;
     target parallel for lastprivate(lp) map(tofrom: lp) with the int gives 192.
   - no other family can witness: CCE craycc 19/20/21 give lp= -1 (the original unchanged) with
     int and long long alike, their lastprivate defect on a for inside a target region
     (cce-c-parallel-for-in-target.c); NVIDIA's guide documents lastprivate on distribute as
     unsupported (HPC Compilers User's Guide 25.11, §7.4, 2.9.4), so nvc is no witness; AFAR
     amdflang stops at "not yet implemented: lastprivate clause in constructs other than
     simd/worksharing-loop/taskloop" on the Fortran form. The expected value rests on the spec
     text and AFAR's own 8-byte and single-leaf controls.
   - relation: stress/afar-c-lastprivate-combined-target-not-mapped.c is the missing implicit map
     (no map clause: lp stays -1 with int and long long alike); this is a second defect, which is
     why that finding's explicit-map control passes only with its long long item .
   - legality: offload.engine.rules accepts it (with the race rule and the restriction checks:
     offload.engine.prerun.check, rerun, data/evidence/lead_probe/logs/legality_new.jsonl), and nvc
     26.9 and 25.11 (NVHPC, not under test for an AFAR finding) compile it with -mp=gpu
     (data/evidence/lead_probe/logs/wingtip_witness.log); the check's other witness, the amdclang front
     end, is AFAR's own and is not counted; no gfortran or gcc is a legality witness.
     Race-free: lp is lastprivate; every iteration writes only its own copy.
   - evidence: data/evidence/lead_probe/leads/ (lp_*.c), runs in data/evidence/lead_probe/logs/leads_*.jsonl;
     reproduction (the gate's four environments by hand, as for
     afar-c-teams-distribute-reduction-first-team.c): MI300A, XNACK 1 and 0, wrong in every run of
     (a), (b), (c) and (d), but the value differs between runs (0, 16246, 337455926, -1176291223,
     ...: the gate reads such a row as nondeterministic); MI250X (tioga39), (a), (b), (d): lp= 0 in
     every run (confirmed). The long long control gave 192 in every environment. */
#include <stdio.h>
#include <omp.h>
int main(void) {
  int lp = -1;
  int dev = -1;
  #pragma omp target teams distribute parallel for lastprivate(lp) map(tofrom: lp)
  for (int i = 1; i <= 64; i++)
    lp = 3 * i;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("lp= %d dev= %d\n", lp, dev);
  return 0;
}
// site:
// title: A lastprivate item smaller than 8 bytes on target teams distribute parallel for comes back as 0 or a garbage value
// end site
