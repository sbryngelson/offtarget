// control: always on the structure only
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
enum { NM = 8 };
struct n1 { int s; int *a; };
struct n0 { int s; struct n1 nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct n0 *r = calloc(1, sizeof *r);
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  r->nx.a = malloc(NM * sizeof(int));
  r->s = 10;
  for (i = 0; i < NM; i++) r->nx.a[i] = 200 + i;
  #pragma omp target map(tofrom: tot) map(always, to: r[0:1]) map(to: r->nx.a[0:8])
  {
    tot += r->s;
    for (int q = 0; q < NM; q++) tot += r->nx.a[q];
  }
  ok = tot == 1638;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
