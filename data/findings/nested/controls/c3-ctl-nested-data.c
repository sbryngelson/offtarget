// control: two nested data constructs
#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>
struct s0 { int v; int *a; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct s0 r;
  r.v = 5; r.a = malloc(4 * sizeof(int));
  for (i = 0; i < 4; i++) r.a[i] = i + 1;
  #pragma acc serial copy(hf)
  hf = acc_on_device(acc_device_host) ? 1 : 0;
  #pragma acc data copyin(r)
  #pragma acc data copyin(r.a[0:4])
  {
    #pragma acc serial copy(tot) present(r)
    {
      tot = r.v;
      for (int q = 0; q < 4; q++) tot += r.a[q];
    }
  }
  ok = tot == 15;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
