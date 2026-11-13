// lead 1 follow-up: reduction(min: l) with the min form, expected 40
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 100000;
  int dev = -1;
  #pragma omp target teams distribute reduction(min: l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l = ((long long) i * 40 < l) ? (long long) i * 40 : l;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", l, dev);
  return 0;
}
