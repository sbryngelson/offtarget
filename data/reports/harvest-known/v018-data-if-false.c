// variant of hk-018: only the target data with an if clause that
// is false and use_device_ptr(p): with if false the device is the host, so p
// keeps the host address (OpenMP 5.2 §13.5).
// expected: check=pass
#include <omp.h>
#include <stdbool.h>
#include <stdio.h>
struct settings { bool staging_buffer; bool is_offload; };
int main(void) {
  enum { N = 512 };
  double buf[N];
  double *p = buf, *seen = NULL;
  struct settings s = {true, true};
#pragma omp target enter data map(to: buf[:N])
#pragma omp target data if (!s.staging_buffer && s.is_offload) use_device_ptr(p)
  { seen = p; }
  printf("host %p seen %p\n", (void *)buf, (void *)seen);
  int ok = (seen == buf);
#pragma omp target exit data map(delete: buf[:N])
  int hk_host = 1;
#pragma omp target map(tofrom: hk_host)
  hk_host = omp_is_initial_device();
  printf("RESULT ran_on_host=%d check=%s\n", hk_host, ok ? "pass" : "fail");
  return 0;
}
