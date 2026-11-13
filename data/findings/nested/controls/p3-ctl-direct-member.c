// control: the member reached without the call
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct n { int *a; struct n *nx; };
#pragma omp declare target
static struct n *child(struct n *r) { return r->nx; }
#pragma omp end declare target
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct n *r = calloc(1, sizeof *r);
  r->nx = calloc(1, sizeof *r->nx);
  r->nx->a = malloc(4 * sizeof(int));
  for (i = 0; i < 4; i++) r->nx->a[i] = i + 1;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target map(tofrom: tot) map(to: r[0:1]) map(to: r->nx[0:1]) map(to: r->nx->a[0:4])
  {
    for (int q = 0; q < 4; q++) tot += r->nx->a[q];
  }
  ok = tot == 10;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
