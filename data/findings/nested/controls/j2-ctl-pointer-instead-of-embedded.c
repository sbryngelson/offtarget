// control: the middle structure reached through a pointer
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct n2 { int *a; };
struct n1 { struct n2 *nx; };
struct n0 { int v; struct n1 *nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct n0 r;
  r.v = 0; r.nx = calloc(1, sizeof *r.nx); r.nx->nx = calloc(1, sizeof *r.nx->nx); r.nx->nx->a = malloc(8 * sizeof(int));
  for (i = 0; i < 8; i++) r.nx->nx->a[i] = 2;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target map(tofrom: tot) map(tofrom: r.nx[0:1]) map(tofrom: r.nx->nx[0:1]) map(tofrom: r.nx->nx->a[0:8])
  {
    for (int q = 0; q < 8; q++) tot += r.nx->nx->a[q];
  }
  ok = tot == 16;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
