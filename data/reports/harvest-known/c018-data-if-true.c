// control for v018-data-if-false: the same target data with an if
// clause that is TRUE: use_device_ptr(p) gives the device address of buf,
// the one omp_get_mapped_ptr returns (OpenMP 5.1 §18.8.11).
// expected: check=pass
#include <omp.h>
#include <stdbool.h>
#include <stdio.h>
struct settings { bool staging_buffer; bool is_offload; };
int main(void) {
  enum { N = 512 };
  double buf[N];
  double *p = buf, *seen = NULL;
  struct settings s = {false, true};
#pragma omp target enter data map(to: buf[:N])
  void *mapped = omp_get_mapped_ptr(buf, omp_get_default_device());
#pragma omp target data if (!s.staging_buffer && s.is_offload) use_device_ptr(p)
  { seen = p; }
  printf("host %p mapped %p seen %p\n", (void *)buf, mapped, (void *)seen);
  int ok = ((void *)seen == mapped);
#pragma omp target exit data map(delete: buf[:N])
  int hk_host = 1;
#pragma omp target map(tofrom: hk_host)
  hk_host = omp_is_initial_device();
  printf("RESULT ran_on_host=%d check=%s\n", hk_host, ok ? "pass" : "fail");
  return 0;
}
