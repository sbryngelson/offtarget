// (the reproduction gate's review queue): NVHPC 25.11 and 26.9 (nvc),
// NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory modes. nvc rejects the
// ordered construct in a target parallel for with the ordered clause
// ("NVC++-S-0155-for must have the ordered clause specified", at the ordered
// region), and
// its front end then INTERMITTENTLY crashes ("nvc-Fatal-.../maintainers/nvcpfe
// TERMINATED by signal 11", compile exit status 2) instead of ending with
// the diagnostic.
// Spec: an ordered region binds to the innermost enclosing worksharing-loop
// region; "An ordered clause with a parameter value equal to one must
// appear on the construct that corresponds to the binding region" (5.2
// §15.10.2 p.331 l.16-17), and "If n is not specified then the behavior is
// as if n is specified with the same value as is specified for the collapse
// clause on the construct" (§4.4.4 p.94 l.18-19), so the program is
// conforming (the ordered clause applies to the for leaf of the combined
// construct, §17.2).
// Vendor: "The ordered block construct is supported only for CPU targets"
// (HPC Compilers User's Guide 25.11 §7.4, 2.17.9;
// data/index/claims/nvidia-hpc-25.11-user-guide-openmp.txt:295, and :194 for the
// ordered clause): documented unsupported, so a diagnostic is expected
// (rule R11c: unsupported, not a bug). Two quality-of-implementation
// defects remain: the diagnostic's text is wrong (it says the for "must
// have the ordered clause specified" when the clause is there), and the
// front end then sometimes crashes. No spec text governs either: a LOWER
// TIER finding (fix; the compile fails either way, with
// the diagnostic printed first, as for nvhpc-parallel-if-in-target-nvvm-ice).
// Expected: "RESULT ran_on_host=0 check=pass", or the diagnostic alone.
// Observed (the source compiled by its absolute path in a fresh directory;
// nvcpfe crashes / compiles, by source):
// - nvc 26.9, -gpu=mem:separate: 31 of 58 = the logs 27 of 53 (wingtip2
//   21/32, wingtip3 4/15, wingtip4 2/6; data/evidence/gate_probe/logs/) + the
//   reproduction gate's 4 reruns, 4 crashes + the
//   stored catalog row, no crash (results/widen/matrix.jsonl);
// - nvc 25.11, -gpu=mem:managed: 26 of 52 = the logs 25 of 47 (wingtip2
//   18/32, wingtip3 3/9, wingtip4 4/6) + the gate's 4 reruns, no crash + the
//   stored row, a crash (in its stderr);
// - nvc 26.9 managed: 6 of 7 (wingtip4 6/6; the stored row did not crash);
// - nvc 25.11 separate: 0 of 7 (wingtip4 0/6; the stored row did not).
// - A compile at a fixed path can crash or not (26.9 separate, a
//   37-character directory: 1 of 3; 25.11 managed, a 45-character path: 1
//   of 3), so this is not a function of the path alone; long paths crash
//   more often (26.9: none below 17 characters of directory name in the
//   length sweep, wingtip2.log). Compiled as the relative name prog.c in the
//   working directory: 0 of 80 (wingtip1.log; that also changes the file
//   name, not only the path). The scripts: data/evidence/gate_probe/wingtip/round1-4/
//   (those runs were not inside compliant.slice: see the scripts' notes).
// Control (same compilers, same flags): the same loop and ordered region
// without target (a host parallel for ordered, which the guide supports)
// compiles and prints "RESULT ran_on_host=1 check=pass" on both releases
// and both memory modes (data/evidence/gate_probe/logs/wingtip4.log).
// Another family: AFAR amdclang compiles the program and prints
// "RESULT ran_on_host=0 check=pass" on MI300A at HSA_XNACK 1 and 0 and on
// MI250X (results/widen/matrix*.jsonl). CCE craycc fails to link it
// (__kmpc_dispatch_init_4, data/findings/catalog/cce-c-ordered-link.c).
// Found by the widened catalog (omp52-c-w-ordered, the cells nvhpc/managed
// and nvhpc269/copy, reproduction-gate verdict environment); the program
// is the catalog program itself.
// NVHPC: nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 $PWD/omp52-c-w-ordered.c
#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  int cnt = 0;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = i + 1;
  }
  #pragma omp target parallel for ordered map(to: a) map(tofrom: b, cnt, host_flag)
  for (int i = 0; i < n; i++) {
    #pragma omp ordered
    {
      b[cnt] = a[i];
      cnt = cnt + 1;
    }
    if (i == 0) host_flag = omp_is_initial_device();
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  ok = ok && (cnt == n);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
// site:
// title: nvc rejects ordered in a target parallel for with the ordered clause, and its front end then crashes intermittently
// end site
