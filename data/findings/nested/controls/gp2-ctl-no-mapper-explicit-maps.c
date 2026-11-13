// control: no mapper, the same two list items in the map clauses
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
enum { NM = 8 };
struct n0 { int s; int *a; };

int main(void)
{
  int hf = 1, i, ha = 0, ok;
  struct n0 r = {0};
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  r.a = malloc(NM * sizeof(int));
  r.s = 10;
  for (i = 0; i < NM; i++) r.a[i] = 100 + i;
  #pragma omp target teams distribute parallel for map(tofrom: r) map(tofrom: r.a[0:NM])
  for (int q = 0; q < NM; q++) r.a[q] = 500 + q;
  for (i = 0; i < NM; i++) ha += r.a[i];
  ok = ha == 4028;
  printf("ha= %d\n", ha);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
