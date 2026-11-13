#include <stdio.h>
#include <omp.h>
int on_dev = 0;
#pragma omp declare target(on_dev)
int main(void) {
  int a[64], b[64], c[64], d[64];
  for (int i = 0; i < 64; i++) { a[i] = i; b[i] = 0; c[i] = 0; d[i] = 0; }
  #pragma omp target
  { on_dev = 1; }
  #pragma omp target teams loop map(to: a) map(from: b)
  for (int i = 0; i < 64; i++) b[i] = 2 * a[i] + on_dev;
  #pragma omp target teams loop map(to: a) map(from: c)
  for (int i = 0; i < 64; i++) c[i] = 2 * a[i] + on_dev;
  #pragma omp target map(to: a) map(from: d)
  {
    #pragma omp teams loop shared(a, d, on_dev)
    for (int i = 0; i < 64; i++) d[i] = 2 * a[i] + on_dev;
  }
  printf("with shared(on_dev): b[1]=%d  without: c[1]=%d  teams loop in "
         "target with shared(on_dev): d[1]=%d (device copy is 1, host copy "
         "%d)\n", b[1], c[1], d[1], on_dev);
  return 0;
}
