// a structure member that is a structure holding a pointer to a structure that holds a pointer: map(tofrom: r) map(tofrom: r.nx.s.a[0:8])
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct n2 { int *a; };
struct n1 { struct n2 s; };
struct n0 { int v; struct n1 nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct n0 r;
  r.v = 0; r.nx.s.a = malloc(8 * sizeof(int));
  for (i = 0; i < 8; i++) r.nx.s.a[i] = 2;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target map(tofrom: tot) map(tofrom: r) map(tofrom: r.nx.s.a[0:8])
  {
    for (int q = 0; q < 8; q++) tot += r.nx.s.a[q];
  }
  ok = tot == 16;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
