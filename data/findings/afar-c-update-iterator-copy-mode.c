// (copy mode for the whole catalog): AFAR amdclang moves no data
// for a target update motion clause with an iterator modifier, at
// HSA_XNACK=0 (separate host and device memory).
// The iterator k = 0:1 has the one value 0 (5.2 §3.2.6 p.67: i0 = begin,
// i0 < end), so to(iterator(k = 0:1): a[k:n - k]) is to(a[0:n]): the
// target update makes the device copy of a consistent with the host
// (5.2 §13.9 p.289). Expected: to iterator: bad= 0 (from_iter: the same
// with from(iterator(k = 0:1): b[k:n - k]) after a device write).
// Observed (tuolumne, MI300A, 2026-10-22, 3 runs each, -O2,
// OMP_TARGET_OFFLOAD=mandatory):
// - AFAR amdclang 24.0.0git at HSA_XNACK=0: to iterator: bad= 64 (and
//   from iterator: bad= 64): nothing is copied; the same update without
//   the iterator, to(a[0:n]), gives bad= 0. Correct at HSA_XNACK=1 (one
//   copy of the data).
// - CCE craycc 19, 20, 21: reject the iterator modifier of to/from (the
//   catalog's to.iterator and from.iterator C programs: "call to
//   undeclared function").
// The catalog's C to.iterator and from.iterator programs (5.2, 6.0) fail
// on AFAR at HSA_XNACK=0 because of it, and so does the C map.iterator
// program: target enter data map(iterator(k = 1:2), to: w[k:n / 2 - k])
// (one value, the section w[1:31]) leaves w[1] not present in copy mode. AFAR amdflang rejects the Fortran
// form ("not yet implemented").
// AFAR: amdclang -fopenmp --offload-arch=gfx942 -fopenmp-version=52 -O2
// Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
#include <stdio.h>
enum { n = 64 };
int main(void) {
  int a[n], b[n], k, bad = 0;
  for (int i = 0; i < n; i++) { a[i] = i; b[i] = 0; }
  #pragma omp target enter data map(to: a) map(alloc: b)
  for (int i = 0; i < n; i++) a[i] += 10;
  #pragma omp target update to(iterator(k = 0:1): a[k:n - k])
  #pragma omp target map(alloc: a, b)
  for (int i = 0; i < n; i++) b[i] = a[i];
  #pragma omp target update from(b)
  #pragma omp target exit data map(release: a, b)
  for (int i = 0; i < n; i++) bad += b[i] != i + 10;
  printf("to iterator: bad= %d\n", bad);
  return 0;
}
// site:
// title: amdclang at HSA_XNACK=0: target update with an iterator modifier moves no data
// control: ../vendor/checks/src/afar/control/afar-c-update-iterator-copy-mode-control.c to(a[0:n]) instead of to(iterator(k = 0:1):
// + a[k:n - k])
// end site
