// lead 1 follow-up 2: 1000 iterations, default teams
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long s = 0;
  int dev = -1;
  #pragma omp target teams distribute reduction(+: s) map(tofrom: s)
  for (int i = 1; i <= 1000; i++)
    s += (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("s= %lld expected= %lld dev= %d\n", s, 20LL * 1000 * (1000 + 1), dev);
  return 0;
}
