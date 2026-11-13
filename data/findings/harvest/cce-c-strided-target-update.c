// # Finding: CCE craycc ignores the stride of an array section in
// # `target update`: from(a[0:4:2]) copies a[0..3], to(a[1:4:2]) a[1..4]
//
// - compilers: CCE craycc 19.0.0, 20.0.2, 21.0.3, -O2: this file on MI300A
//   gfx942 and MI250X gfx90a (HSA_XNACK=0); the 25 non-holdout upstream
//   tests on both
// - expected: a: 10 1 12 3 14 5 16 7 / strided bad= 0 contiguous bad= 0
//   elementwise bad= 0
// - actual: a: 10 11 12 13 4 5 6 7 / strided bad= 4 (the first 4 elements,
//   not every second one); `to(a[1:4:2])` likewise writes a[1..4] (a probe,
//   results/harvest/probe/src/strided_to.c and f1f2.jsonl, git-ignored)
// - rule: "The list items may include array sections with stride
//   expressions ... If a list item is an array or array section then it is
//   treated as if it is replaced by each of its array elements in the
//   clause" (OpenMP 5.2 §5.9 p.165 l.13-17), and a[0:4:2] denotes the
//   elements "{ lower-bound, lower-bound + stride, lower-bound + 2 * stride,
//   ... , lower-bound + ((length - 1) * stride) }" (5.2 §3.2.5 p.64
//   l.22-23): a[0], a[2], a[4], a[6].
// - copy mode only: with storage shared between host and device
//   (HSA_XNACK=1) every device write is visible, so elements outside the
//   section may differ legitimately (17 of the 25 non-holdout upstream tests
//   fail there on AFAR and CCE alike; they are copy-only in
//   catalog/harvest_copy_only.yaml).
// - same-compiler controls (correct): from(b[0:4]) (contiguous); the four
//   elements as four `target update from(c[k:1])`.
// - other families: AFAR amdclang correct on this file and on all 25
//   non-holdout upstream tests (gfx942 and gfx90a, X0). NVHPC nvc 25.11 and
//   26.9 reject the stride ("expected a ]", this file and the 25 tests, both
//   modes).
// - vendor claim: "Non-contiguous updates are supported for normal array
//   slice expressions that specify a lower bound, upper bound, and optional
//   stride" (CCE 19.0.0, 20.0.2, 21.0.3 intro_openmp, data/index/claims/).
// - upstream: the 25 non-holdout tests of llvm-project
//   offload/test/offloading/strided_update/ fail on every CCE cell at X0
//   (gfx942 and gfx90a; gate confirmed).
// - legality: offload.engine.prerun.check accepts it (the rules and the AFAR
//   clang front end).
// CCE:  craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
//       -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -fopenmp-version=52 -O2
// Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
#include <stdio.h>
#include <omp.h>
int main(void) {
  double a[8], b[8], c[8];
  for (int i = 0; i < 8; i++) a[i] = b[i] = c[i] = i;
  int on_host = 1, bad_a = 0, bad_b = 0, bad_c = 0;
#pragma omp target data map(to: a[0:8], b[0:8], c[0:8])
  {
#pragma omp target map(from: on_host)
    {
      on_host = omp_is_initial_device();
      for (int i = 0; i < 8; i++) { a[i] += 10; b[i] += 10; c[i] += 10; }
    }
#pragma omp target update from(a[0:4:2])
#pragma omp target update from(b[0:4])
#pragma omp target update from(c[0:1])
#pragma omp target update from(c[2:1])
#pragma omp target update from(c[4:1])
#pragma omp target update from(c[6:1])
  }
  for (int i = 0; i < 8; i++) {
    bad_a += a[i] != (i % 2 == 0 ? i + 10 : i);
    bad_b += b[i] != (i < 4 ? i + 10 : i);
    bad_c += c[i] != (i % 2 == 0 ? i + 10 : i);
  }
  printf("a:");
  for (int i = 0; i < 8; i++) printf(" %g", a[i]);
  printf("\nstrided bad= %d contiguous bad= %d elementwise bad= %d\n", bad_a, bad_b, bad_c);
  printf("RESULT ran_on_host=%d check=%s\n", on_host, bad_a == 0 ? "pass" : "fail");
  return 0;
}
// site:
// title: target update of a strided array section (C) copies the contiguous range instead of every second element
// end site
