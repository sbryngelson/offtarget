// GCC review I3 control: omp52-c-clause-in_reduction-ior with the target in an explicit task
// (no taskgroup, no in_reduction; s mapped tofrom). Derived from: offload.engine.c_gen (OpenMP 5.2, C11): the C port (offload.engine.f2c) of omp52-clause-in_reduction-ior. Do not edit.
// id: omp52-c-clause-in_reduction-ior
// primary atom: omp.clause.in_reduction.ior
// legal: yes
// observable: yes
// ran_on_host: inside the target region of interest
// evidence: construct
// needs: none
// std: c11
#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n];
  int b[n];
  int ref[n];
  int host_flag;
  bool ok;
  int s;
  int sref;
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
  s = 0;
  sref = 0;
  for (int i = 1; i <= n; i++) {
    sref = (sref | a[i - 1]);
  }
  #pragma omp task shared(a, b, host_flag, s)
  {
    #pragma omp target map(to: a) map(from: b) map(tofrom: host_flag) map(tofrom: s)
    {
      host_flag = (omp_is_initial_device() ? 1 : 0);
      for (int i = 1; i <= n; i++) {
        b[i - 1] = 2 * a[i - 1] + 1;
        s = (s | a[i - 1]);
      }
    }
  }
  #pragma omp taskwait
  bool t1_ = true;
  for (int k2_ = 0; k2_ < n; k2_++)
    t1_ = t1_ && (b[k2_] == ref[k2_]);
  ok = t1_ && (s == sref);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
