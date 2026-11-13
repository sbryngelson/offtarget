// control: only the member array in the update (v stays)
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct s { int v; int *a; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct s *r = malloc(sizeof *r);
  r->v = 5; r->a = malloc(4 * sizeof(int));
  for (i = 0; i < 4; i++) r->a[i] = i + 1;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target enter data map(to: r[0:1]) map(to: r->a[0:4])
  for (i = 0; i < 4; i++) r->a[i] = 10 * (i + 1);
  #pragma omp target update to(r->a[0:4])
  #pragma omp target map(tofrom: tot)
  { tot = r->v; for (int q = 0; q < 4; q++) tot += r->a[q]; }
  #pragma omp target exit data map(release: r->a[0:4]) map(release: r[0:1])
  ok = tot == 105;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
