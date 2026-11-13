#include <stdio.h>
int main(void) {
  int b[64], c[64], d[64], t = -1, x = 0;
  for (int i = 0; i < 64; i++) { b[i] = 0; c[i] = 0; d[i] = -1; }
  #pragma omp target map(from: b, c, d) map(tofrom: t, x)
  {
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < 64; i++) b[i] = i + 1;
    #pragma omp parallel for lastprivate(t)
    for (int i = 0; i < 64; i++) { c[i] = i + 1; t = i; }
    #pragma omp parallel for linear(x: 1)
    for (int i = 0; i < 64; i++) { d[i] = x; x++; }
  }
  int nb = 0, nd = 0;
  for (int i = 0; i < 64; i++) { nb += b[i] == i + 1; nd += d[i] == i; }
  printf("static %d of 64; lastprivate t=%d; linear %d of 64, x=%d\n",
         nb, t, nd, x);
  return 0;
}
