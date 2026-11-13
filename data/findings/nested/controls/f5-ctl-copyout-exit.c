// control: the pointer array leaves with copyout instead of delete
#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>
struct s1 { int *a; };
struct s0 { int v; struct s1 **nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct s0 r;
  r.v = 5;
  r.nx = malloc(2 * sizeof *r.nx);
  for (i = 0; i < 2; i++) {
    r.nx[i] = malloc(sizeof *r.nx[i]);
    r.nx[i]->a = malloc(4 * sizeof(int));
    for (int q = 0; q < 4; q++) r.nx[i]->a[q] = 10 * (i + 1) + q;
  }
  #pragma acc serial copy(hf)
  hf = acc_on_device(acc_device_host) ? 1 : 0;
  #pragma acc enter data copyin(r)
  #pragma acc enter data copyin(r.nx[0:2])
  #pragma acc serial copy(tot) present(r)
  {
    tot = r.v;
    tot += 1;
  }
  #pragma acc exit data copyout(r.nx[0:2])
  #pragma acc exit data delete(r)
  ok = tot == 6;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
