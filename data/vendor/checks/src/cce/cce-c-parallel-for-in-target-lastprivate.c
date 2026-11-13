#include <stdio.h>
int main(void) {
  int c[64], t = -1;
  for (int i = 0; i < 64; i++) c[i] = 0;
  #pragma omp target map(from: c) map(tofrom: t)
  {
    #pragma omp parallel for lastprivate(t)
    for (int i = 0; i < 64; i++) { c[i] = i + 1; t = i; }
  }
  printf("lastprivate t=%d c[63]=%d\n", t, c[63]);
  return 0;
}
