// NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80; the hang is
// in the compile on the x86-64 host), both memory modes: nvc does not
// finish compiling this program: its C front end (nvcpfe) runs until
// killed (more than 60 s here; the catalog's 900 s compile timeout in both
// memory modes). Without dist_schedule(static, 4), or with either of the
// two `if (i == 1)` statements removed, it compiles in a second.
// Spec: with dist_schedule(static, chunk_size) the chunks "are assigned to
// the initial teams of the league in a round-robin fashion in the order of
// the initial team number" (5.2 §11.6.1 p.256); the program is legal.
// Vendor: "The private, firstprivate, collapse, and dist_schedule(static [
// ,chunksize]) clauses are supported" (HPC Compilers User's Guide 25.11
// §7.4, 2.9.4).
// Expected: the compile ends (and the run prints "nt=<teams> host_flag=0").
// Observed (2026-10-24, nvc 25.11-0, -O2, with -gpu=mem:separate and with
// the default): `timeout 60 nvc ...` ends with status 124.
// Found by the catalog (omp52/60-c-clause-dist_schedule-chunk_size:
// compile_timeout, confirmer R10b-own-link-or-hang); reduced with a
// line-deletion script, then by hand.
// NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
// the same flags): still present -- the same: `timeout 120 nvc` ends with 124 in both modes.
// Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
// each with its own runtime libraries (LD_LIBRARY_PATH = the release's
// compilers/lib; the first 26.9 runs had loaded 25.11's): still present
// on both releases, the same output.
// NVHPC: nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
#include <stdio.h>
#include <omp.h>
int main(void) {
  int nt = -1, host_flag = 1;
  #pragma omp target teams distribute parallel for map(from: nt, host_flag) dist_schedule(static, 4)
  for (int i = 1; i <= 64; i++) {
    if (i == 1) nt = omp_get_num_teams();
    if (i == 1) host_flag = (omp_is_initial_device() ? 1 : 0);
  }
  printf("nt=%d host_flag=%d\n", nt, host_flag);
  return 0;
}
// site:
// title: nvc -mp=gpu: compile does not finish with dist_schedule(static, 4) on target teams distribute parallel for
// control: ../vendor/checks/src/nvhpc/control/nvhpc-c-dist-schedule-chunk-compile-hang-control.c dist_schedule(static, 4) removed
// end site
