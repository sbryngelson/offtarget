#include <stdio.h>
#include <omp.h>
int main(void) {
  int a[64], b[64];
  for (int i = 0; i < 64; i++) { a[i] = i; b[i] = 0; }
  #pragma omp target data map(to: a)
  {
    #pragma omp target map(to: a) map(from: b)
    {
      for (int i = 0; i < 64; i++) b[i] = 2 * a[i];
    }
  }
  int ok = 1;
  for (int i = 0; i < 64; i++) ok = ok && b[i] == 2 * i;
  printf("ok=%d\n", ok);
  return 0;
}
