// # Finding: craycc -flto drops the OpenMP offload code
//
// - compilers: CCE craycc 19.0.0, 20.0.2, 21.0.3 (C), MI300A (gfx942) and MI250X (gfx90a)
// - build: the catalog's CCE C recipe (offload/engine/toolchains.py C_FLAGS) plus `-O2 -flto`;
//   without -flto the same file is correct on every CCE release; AFAR amdclang -flto is correct
// - expected: sum= 2016 dev= 1 (a target teams distribute loop fills a[i] = i on the device)
// - build flags: -O2 -flto
//   (read by the confirmer, offload.engine.confirm.programs.file_ref, which adds them to every
//   build of this reproducer; its -O0 control keeps -flto)
// - actual (OMP_TARGET_OFFLOAD=mandatory): the program builds, then exits 255 with "ACC: OpenMP
//   offload failed when OMP_TARGET_OFFLOAD=MANDATORY at address 0x200a...". Observed cells:
//   MI300A HSA_XNACK 1 (CCE 19/20/21, audit runs.jsonl), MI250X HSA_XNACK 0 (Tioga, CCE 19/20/21,
//   runs-tioga.jsonl), and MI300A HSA_XNACK 0 (CCE 19 and 21; CCE 19/20/21,
//   runs-fix2.jsonl). Under
//   OMP_TARGET_OFFLOAD=default the -flto binary runs the region on the host: "sum= 2016 dev= 0".
// - the offload code is absent (readelf/nm of the executables, CCE 19.0.0 and 21.0.3,
//   MI300A): without -flto the binary has a cray_omp_offloading_entries section, the
//   .offloading.entry.__omp_offloading_* symbols and 7 strings naming amdgcn/gfx942; with -O2 -flto
//   the entries section and the entry symbols are gone (only the .region_id symbols remain) and no
//   amdgcn/gfx942 string is left. AFAR amdclang -flto keeps .llvm.offloading and its entries and
//   runs on the device. Not run: the non--flto control on MI250X.
// - evidence: results/stress/audit/runs.jsonl and runs-tioga.jsonl (tools/campaigns/stress_audit.py on
//   data/reports/fuzz-stress-audit/r8-craycc-flto.c); the audit rerun's runs are committed as
//   data/reports/fuzz-stress-audit/rereview-1-lto.jsonl. In the stress sweeps every C program of
//   the `lto` variant failed the same way (s1-var, 3 CCE releases x 3 layouts), and every other
//   variant agreed
// - confirmer (which carries the "build flags" line above into every build): on CCE 19 in
//   both modes (`tools/confirm.py case <this file> --toolchain cce19 --mode unified|copy --expected
//   "sum= 2016 dev= 1" --run`, 2026-10-25) the verdict is needs_human (R22-expected-weak): CCE 19, 20
//   and 21 built with -O2 -flto exit 255 on every run and AFAR amdclang -O2 -flto prints the expected
//   value, but the expected value rests on the stated value alone (no sequential elision of this C
//   program), which the rules call provisional. Before the confirmer could not add -flto
//   (data/reports/fuzz-stress.md). The installed CCE documentation has no craycc page
//   and does not say that -flto is unsupported with offload; if HPE documents that, this is a
//   documented limitation, not a defect.
// - legality: legal C11 / OpenMP 5.0 by reading: a[0:64] is mapped from and each iteration writes
//   its own element; dev is mapped tofrom and written by the one initial thread of a target region
//   (amdclang -fopenmp -fsyntax-only, not of the family under test, accepts it)
/* Audit: craycc -flto with OpenMP offload. A target teams
   distribute loop; built with -flto it must still run on the device.
   Expected (with and without -flto): sum= 2016 dev= 1 */
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long a[64], sum = 0;
  int dev = -1;
  #pragma omp target teams distribute map(from: a[0:64])
  for (int i = 0; i < 64; i++)
    a[i] = i;
  for (int i = 0; i < 64; i++)
    sum += a[i];
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("sum= %lld dev= %d\n", sum, dev);
  return 0;
}
// site:
// title: craycc -flto: the offload code is dropped; the program fails under OMP_TARGET_OFFLOAD=mandatory
// control: ../vendor/checks/src/cce/control/cce-c-flto-offload-dropped-control.c built without -flto (-O2)
// end site
// spec (requirement): a target construct includes an executable region that is executed on a device, and with
//   OMP_TARGET_OFFLOAD=mandatory a construct that cannot use its device is an error instead of a host fallback. The -flto option
//   is a vendor build option that OpenMP does not mention, so there is no OpenMP text on link-time optimization itself; the
//   nearest normative text is the device execution of the target region.
// "The target construct provides a superset of the functionality provided by the target data directive, except for the
//   use_device_ptr and use_device_addr clauses. The functionality added to the target directive is the inclusion of an executable
//   region to be executed on a device." (5.2 §13.8 p.284 l.11-13)
// "The mandatory value specifies that the effect of any device construct or device memory routine that uses a device that is
//   unavailable or not supported by the implementation, or uses a non-conforming device number, is as if the omp_invalid_device
//   device number was used." (5.2 §21.2.8 p.610 l.28-30)
// spec (this program): the target teams distribute region must still execute on the device in a program built with -flto; the
//   binary has lost its offload entries, so OMP_TARGET_OFFLOAD=mandatory aborts (the default setting silently runs the region on
//   the host, dev= 0).
