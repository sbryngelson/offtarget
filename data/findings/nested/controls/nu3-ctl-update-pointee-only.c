// control: target update from() of the pointee section only
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
enum { NM = 8 };
struct n0 { int s; int *a; };
int main(void)
{
  int hf = 1, i, ha = 0, ok;
  struct n0 *r = calloc(1, sizeof *r);
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  r->a = malloc(NM * sizeof(int));
  r->s = -1;
  for (i = 0; i < NM; i++) r->a[i] = -1;
  #pragma omp target enter data map(alloc: r[0:1])
  #pragma omp target enter data map(alloc: r->a[0:8])
  #pragma omp target teams distribute parallel for
  for (int q = 0; q < NM; q++) r->a[q] = 500 + q;
  #pragma omp target update from(r->a[0:8])
  #pragma omp target exit data map(delete: r->a[0:8])
  #pragma omp target exit data map(delete: r[0:1])
  for (i = 0; i < NM; i++) ha += r->a[i];
  ok = ha == 4028;
  printf("ha= %d\n", ha);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
