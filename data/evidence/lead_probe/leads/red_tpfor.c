// lead 1: target parallel for (no teams)
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0;
  int dev = -1;
  #pragma omp target parallel for reduction(max: l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l = (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", (long long) l, dev);
  return 0;
}
