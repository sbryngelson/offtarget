// lead 1 follow-up: reduction(max: l) on a double, expected 2560
#include <stdio.h>
#include <omp.h>
int main(void) {
  double l = 0;
  int dev = -1;
  #pragma omp target teams distribute reduction(max: l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l = (i * 40.0 > l) ? i * 40.0 : l;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %g dev= %d\n", l, dev);
  return 0;
}
