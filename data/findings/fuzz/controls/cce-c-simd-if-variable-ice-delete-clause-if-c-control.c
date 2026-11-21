// Control of cce-c-simd-if-variable-ice.c: delete clause if(c) at line 9; one change from the reduction; passes on cce21/0, cce19/0.
// Every step passed the legality rules witness (offload.engine.prerun rules); the front-end witness (offload.engine.prerun.check) is still to run on Tuolumne.
#include <stdio.h>
#include <omp.h>
enum { n = 64 };
int main(void) {
  int a[n], host = 1, c = 0;
  #pragma omp target map(tofrom: host)
  {
    host = omp_is_initial_device();
    #pragma omp simd
    for (int i = 0; i < n; i++) a[i] = 2 * i;
  }
  int ok = 1;
  printf("RESULT ran_on_host=%d check=%s\n", host, ok ? "pass" : "fail");
  return 0;
}
