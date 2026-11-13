// Control of apps/gcc-acc-c-tile-partial-tiles-wrong.c: collapse(2) in place of tile(32, 32) (correct on gcc_g90 and gcc_sm80).
#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>

int main(void) {
  const int n = 100;
  int *a = malloc(n * n * sizeof(int));
  int bad = 0, host_flag = 1;
  for (int k = 0; k < n * n; k++) a[k] = 0;
#pragma acc parallel loop collapse(2) copy(a[0:n*n])
  for (int i = 1; i < n - 1; i++)
    for (int j = 1; j < n - 1; j++)
      a[i * n + j] += i + j;
#pragma acc parallel num_gangs(1) copy(host_flag)
  host_flag = acc_on_device(acc_device_host);
  for (int i = 0; i < n; i++)
    for (int j = 0; j < n; j++) {
      int want = (i > 0 && i < n - 1 && j > 0 && j < n - 1) ? i + j : 0;
      bad += a[i * n + j] != want;
    }
  printf("bad= %d\n", bad);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, bad ? "fail" : "pass");
  free(a);
  return 0;
}
