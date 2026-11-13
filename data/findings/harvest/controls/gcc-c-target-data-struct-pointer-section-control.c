// Control of harvest/gcc-c-target-data-struct-pointer-section-ice.c: the same three list items with the pointer member listed
// before its array section (compiles; correct on gcc_g90 and gcc_sm80).
#include <stdio.h>
#include <omp.h>

struct S { int a; int *p; };

int main(void) {
  int v[4] = {1, 2, 3, 4}, host_flag = 1, sum = 0;
  struct S s;
  s.a = 10;
  s.p = v;
  int *q = v;
  /* control: the pointer member first, then its array section, then the other member */
#pragma omp target data map(s.p, s.p[:4], s.a)
  {
#pragma omp target map(tofrom: q[:4], host_flag)
    {
      host_flag = omp_is_initial_device();
      for (int i = 0; i < 4; i++) q[i] += 1;
    }
  }
  for (int i = 0; i < 4; i++) sum += v[i];
  printf("sum= %d\n", sum);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, sum == 14 ? "pass" : "fail");
  return 0;
}
