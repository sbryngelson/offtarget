// lead 1 follow-up: reduction(max: l), the if form, expected 2560
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0;
  int dev = -1;
  #pragma omp target teams distribute reduction(max: l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    if ((long long) i * 40 > l) l = (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", l, dev);
  return 0;
}
