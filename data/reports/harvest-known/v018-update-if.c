// variant of hk-018: only the target update with if(s.a && s.b),
// once true (the update runs) and once false (it must not run).
// expected: check=pass
#include <omp.h>
#include <stdbool.h>
#include <stdio.h>
struct settings { bool staging_buffer; bool is_offload; };
int main(void) {
  enum { N = 512 };
  double buf[N];
  int ok = 1;
  struct settings s = {true, true};
#pragma omp target enter data map(alloc: buf[:N])
#pragma omp target teams distribute parallel for
  for (int i = 0; i < N; ++i) buf[i] = 2.0 * i;
#pragma omp target update if (s.staging_buffer && s.is_offload) from(buf[:N])
  for (int i = 0; i < N; ++i) if (buf[i] != 2.0 * i) ok = 0;
  printf("after true: ok = %d\n", ok);
  s.staging_buffer = false;
#pragma omp target teams distribute parallel for
  for (int i = 0; i < N; ++i) buf[i] = 3.0 * i;
#pragma omp target update if (s.staging_buffer && s.is_offload) from(buf[:N])
  for (int i = 0; i < N; ++i) if (buf[i] != 2.0 * i) ok = 0;
  printf("after false: ok = %d\n", ok);
#pragma omp target exit data map(delete: buf[:N])
  int hk_host = 1;
#pragma omp target map(tofrom: hk_host)
  hk_host = omp_is_initial_device();
  printf("RESULT ran_on_host=%d check=%s\n", hk_host, ok ? "pass" : "fail");
  return 0;
}
