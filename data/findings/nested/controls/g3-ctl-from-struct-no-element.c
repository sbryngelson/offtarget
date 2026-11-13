// control: map(from: r) alone
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct s1 { int a[4]; };
struct s0 { int v; struct s1 *nx[2]; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct s0 r;
  r.v = 1;
  for (i = 0; i < 2; i++) {
    r.nx[i] = malloc(sizeof *r.nx[i]);
    for (int q = 0; q < 4; q++) r.nx[i]->a[q] = 10 * (i + 1) + q;
  }
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target map(tofrom: tot) map(from: r)
  {
    tot = r.v;
    tot = 7; r.v = 2;
  }
  ok = tot == 7;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
