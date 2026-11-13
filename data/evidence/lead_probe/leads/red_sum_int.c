// lead 1 follow-up: reduction(+: l) int, expected 2080
#include <stdio.h>
#include <omp.h>
int main(void) {
  int l = 0;
  int dev = -1;
  #pragma omp target teams distribute reduction(+: l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l += i;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %d dev= %d\n", l, dev);
  return 0;
}
