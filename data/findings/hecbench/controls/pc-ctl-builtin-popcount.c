#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define M1 0x5555555555555555UL
#define M2 0x3333333333333333UL
#define M4 0x0f0f0f0f0f0f0f0fUL
#define H01 0x0101010101010101UL

int main(void)
{
  const int length = 1024;
  int hf = 1, bad = 0;
  unsigned long *data = malloc(length * sizeof(unsigned long));
  int *result = malloc(length * sizeof(int));
  for (int i = 0; i < length; i++)
    data[i] = (unsigned long)(i + 1) * 0x9E3779B97F4A7C15UL;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;

  #pragma omp target map(to: data[0:length]) map(from: result[0:length])
  for (int i = 0; i < length; i++) {
    unsigned long x = data[i];
    result[i] = __builtin_popcountll(x);
  }

  for (int i = 0; i < length; i++) {
    int count = 0;
    for (unsigned long y = data[i]; y; count++) y &= y - 1;
    if (count != result[i]) bad++;
  }
  printf("bad= %d\n", bad);
  printf("RESULT ran_on_host=%d check=%s\n", hf, bad == 0 ? "pass" : "fail");
  free(data);
  free(result);
  return 0;
}
