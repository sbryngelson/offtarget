// Control of harvest/cce-c-implicit-struct-map-partly-present.c: s.big added to the target data map, so the whole structure is
// present when the target region maps it implicitly (correct on AFAR, CCE and NVHPC).
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
#define N 100
struct foo { char big[200000]; float a, b; float *p; };
#pragma omp begin declare target
void saxpy(struct foo *s) { for (int i = 0; i < N; i++) s->p[i] = s->p[i] * s->a + s->b; }
#pragma omp end declare target
int main(void) {
  struct foo s;
  int dev = 0;
  s.a = 2; s.b = 4; s.p = malloc(sizeof(float) * N);
  for (int i = 0; i < N; i++) s.p[i] = i;
#pragma omp target data map(s.big, s.p[:N], s.p, s.a, s.b)
#pragma omp target map(from: dev)
  { saxpy(&s); dev = !omp_is_initial_device(); }
  printf("%.0f %.0f dev= %d\n", s.p[0], s.p[N - 1], dev);
  int ok = s.p[0] == 4 && s.p[N - 1] == 202;
  printf("RESULT ran_on_host=%d check=%s\n", !dev, ok ? "pass" : "fail");
  return 0;
}
