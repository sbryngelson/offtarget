// control: the member is embedded, not a pointer
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct s1 { int a[8]; };
struct s0 { int v; struct s1 nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  struct s0 *r = malloc(sizeof *r);
  r->v = 10;
  for (i = 0; i < 8; i++) r->nx.a[i] = 200 + i;
  #pragma omp target map(tofrom: tot) map(to: r[0:1])
  {
    tot += r->v;
    for (int q = 0; q < 8; q++) tot += r->nx.a[q];
  }
  ok = tot == 1638;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
