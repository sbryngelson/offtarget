// # Finding (GCC 16.2, LLVM/AOMP harvest): C array sections with a stride are rejected ("expected ']' before ':' token")
//
// - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
//   separate memory only; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); -foffload=nvptx-none
//   -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: rejected: expected ']' before ':' token
// - observed: `error: expected ']' before ':' token` at the stride of `a[0:8:2]` in the target update directive, on both targets
// - expected: compiles; prints `bad= 0` and `RESULT ran_on_host=0 check=pass` (only the even elements come back)
// - rule: in C, an array section is written `[ lower-bound : length : stride]` (5.2 §3.2.5 p.64 l.3-5; the stride form is OpenMP
//   5.0's).
// - GCC's documentation: libgomp.texi, OpenMP 5.0 table: "Array sections with non-unit strides in C and C++: N" (not supported,
//   documented).
// - other families: AFAR runs the harvested programs correctly (copy mode, MI300A and MI250X); CCE 19/20/21 and NVHPC fail them
//   (cce-c-strided-target-update.c: CCE behaves incorrectly; NVHPC rejects). The site's finding matrix runs this file on every
//   compiler: AFAR runs it correctly in copy mode and prints `bad= 8` in unified mode (HSA_XNACK=1), which this file's check
//   does not allow but the specification does ("The corresponding variable in the device data environment may share storage with
//   the original variable. Writes to the corresponding variable may alter the value of the original variable", 5.2 §1.4.2 p.28
//   l.12-13): the odd elements change too. The check holds for separate memory only, the memory GCC has.
// - harvested programs (50 cells (25 gcc_g90, 25 gcc_sm80); gate: confirmed 50; confirmer: compiler_bug (R11-compile-rejection) 28,
//   needs_human (R12b-compile-undecided) 22): hv-llvm-offloading-strided-update-strided-update-count-expression,
//   hv-llvm-offloading-strided-update-strided-update-from, hv-llvm-offloading-strided-update-strided-update-from-pointer,
//   hv-llvm-offloading-strided-update-strided-update-multidim-offset,
//   hv-llvm-offloading-strided-update-strided-update-multiple-arrays-variable-stride,
//   hv-llvm-offloading-strided-update-strided-update-multiple-from, hv-llvm-offloading-strided-update-strided-update-multiple-to,
//   hv-llvm-offloading-strided-update-strided-update-partial-from,
//   hv-llvm-offloading-strided-update-strided-update-ptr-multiple-from,
//   hv-llvm-offloading-strided-update-strided-update-ptr-multiple-to,
//   hv-llvm-offloading-strided-update-strided-update-ptr-partial-from,
//   hv-llvm-offloading-strided-update-strided-update-ptr-partial-to,
//   hv-llvm-offloading-strided-update-strided-update-ptr-variable-count-and-stride,
//   hv-llvm-offloading-strided-update-strided-update-ptr-variable-stride,
//   hv-llvm-offloading-strided-update-strided-update-struct-count-expression,
//   hv-llvm-offloading-strided-update-strided-update-struct-from,
//   hv-llvm-offloading-strided-update-strided-update-struct-multiple-from,
//   hv-llvm-offloading-strided-update-strided-update-struct-multiple-to,
//   hv-llvm-offloading-strided-update-strided-update-struct-partial-from,
//   hv-llvm-offloading-strided-update-strided-update-struct-partial-to, hv-llvm-offloading-strided-update-strided-update-struct-to,
//   hv-llvm-offloading-strided-update-strided-update-struct-variable-stride, hv-llvm-offloading-strided-update-strided-update-to,
//   hv-llvm-offloading-strided-update-strided-update-to-pointer,
//   hv-llvm-offloading-strided-update-strided-update-variable-stride-misc
// - legality: the pre-run check (offload.engine.prerun.check: the rules and AFAR's front end, two witnesses) accepts the harvested
//   programs. GCC is a compiler under test only and never a legality witness.
#include <stdio.h>
#include <omp.h>

int main(void) {
  int a[16], host_flag = 1, bad = 0;
  for (int i = 0; i < 16; i++) a[i] = -1;
#pragma omp target enter data map(to: a)
#pragma omp target map(tofrom: host_flag)
  {
    host_flag = omp_is_initial_device();
    for (int i = 0; i < 16; i++) a[i] = i;
  }
  /* every second element of the first 16: a[0], a[2], ..., a[14] */
#pragma omp target update from(a[0:8:2])
  for (int i = 0; i < 16; i++) bad += (i % 2 == 0) ? (a[i] != i) : (a[i] != -1);
#pragma omp target exit data map(delete: a)
  printf("bad= %d\n", bad);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, bad ? "fail" : "pass");
  return 0;
}
// site:
// title: C array sections with a stride ([lower-bound:length:stride]) are rejected
// summary: OpenMP 5.0 added a stride to C array sections. GCC 16.2 rejects a strided section in a target update from clause
// + ("expected ']' before ':' token") for both offload targets; GCC's documentation lists non-unit strides in C and C++ as not
// + supported. AFAR runs the harvested programs correctly (and this file in copy mode; the file's check assumes separate
// + memory).
// end site
