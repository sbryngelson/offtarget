#include <stdio.h>
int main(void) {
  int b[64];
  for (int i = 0; i < 64; i++) b[i] = 0;
  #pragma omp target map(from: b)
  {
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < 64; i++) b[i] = i + 1;
  }
  int nb = 0;
  for (int i = 0; i < 64; i++) nb += b[i] == i + 1;
  printf("static %d of 64\n", nb);
  return 0;
}
