#include <stdio.h>
int main(void) {
  int b[64];
  for (int i = 0; i < 64; i++) b[i] = 0;
  #pragma omp target teams distribute parallel for map(from: b) \
      num_teams(4) dist_schedule(static)
  for (int i = 0; i < 64; i++) b[i] = i + 1;
  int n = 0;
  for (int i = 0; i < 64; i++) n += b[i] == i + 1;
  printf("%d of 64\n", n);
  return 0;
}
