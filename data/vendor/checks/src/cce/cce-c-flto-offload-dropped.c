#include <stdio.h>
#include <omp.h>
int main(void) {
  long long a[64], sum = 0;
  int dev = -1;
  #pragma omp target teams distribute map(from: a[0:64])
  for (int i = 0; i < 64; i++)
    a[i] = i;
  for (int i = 0; i < 64; i++)
    sum += a[i];
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("sum= %lld dev= %d\n", sum, dev);
  return 0;
}
