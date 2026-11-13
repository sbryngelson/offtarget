#include <stdio.h>
int main(void) {
  int d[64], x = 0;
  for (int i = 0; i < 64; i++) d[i] = -1;
  #pragma omp target map(from: d) map(tofrom: x)
  {
    #pragma omp parallel for linear(x: 1)
    for (int i = 0; i < 64; i++) { d[i] = x; x++; }
  }
  int nd = 0;
  for (int i = 0; i < 64; i++) nd += d[i] == i;
  printf("linear %d of 64, x=%d\n", nd, x);
  return 0;
}
