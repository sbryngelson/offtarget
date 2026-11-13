#include <stdio.h>
#include <stdbool.h>
#include <omp.h>
int main(void) {
  int a[64];
  int nthr = 0;
  bool use_par = false;
  for (int i = 0; i < 64; i++) a[i] = 0;
  #pragma omp target map(tofrom: a) map(from: nthr)
  {
    #pragma omp parallel for
    for (int i = 0; i < 64; i++) {
      a[i] = i + 1;
      if (i == 0) nthr = omp_get_num_threads();
    }
  }
  int s = 0;
  for (int i = 0; i < 64; i++) s += a[i];
  printf("sum %d nthr %d\n", s, nthr);
  return 0;
}
