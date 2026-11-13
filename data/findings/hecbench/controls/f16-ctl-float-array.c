#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

typedef float half_t;

int main(void)
{
  const int size = 1024;
  int hf = 1;
  half_t *ax = malloc(size * sizeof(half_t));
  float *out = malloc(size * sizeof(float));
  float total = 0.f;
  for (int i = 0; i < size; i++) { ax[i] = 2; out[i] = 0; }
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;

  #pragma omp target map(to: ax[0:size]) map(from: out[0:size])
  for (int i = 0; i < size; i++)
    out[i] = (float)ax[i];

  for (int i = 0; i < size; i++) total += out[i];
  printf("total= %f\n", total);
  printf("RESULT ran_on_host=%d check=%s\n", hf, total == 2048.f ? "pass" : "fail");
  free(ax);
  free(out);
  return 0;
}
