#include <stdio.h>
int main(void) {
  int a[64], b[64];
  for (int i = 0; i < 64; i++) a[i] = i;
  #pragma omp target data map(to: a)
  #pragma omp target map(present, to: a) map(from: b)
  for (int i = 0; i < 64; i++)
    b[i] = a[i];
  printf("continued after map(present) of an absent a: b[63]=%d\n", b[63]);
  return 0;
}
