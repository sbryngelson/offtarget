// lead 1 follow-up 2: target teams reduction(+: s) with a distribute inside
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long s = 0;
  int dev = -1;
  #pragma omp target teams reduction(+: s) map(tofrom: s)
  #pragma omp distribute
  for (int i = 1; i <= 64; i++)
    s += (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("s= %lld expected= %lld dev= %d\n", s, 20LL * 64 * (64 + 1), dev);
  return 0;
}
