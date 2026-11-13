// lead 1: reduction(max: l) with the body l = max(l, i * 40)
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0;
  int dev = -1;
  #pragma omp target teams distribute reduction(max: l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l = ((long long) i * 40 > l) ? (long long) i * 40 : l;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", (long long) l, dev);
  return 0;
}
