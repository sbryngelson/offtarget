#include <stdio.h>
#include <omp.h>
enum { n = 64 };
int main(void) {
  int a[n], b[n], d = omp_get_default_device();
  for (int i = 0; i < n; i++) { a[i] = i; b[i] = 0; }
  #pragma omp target enter data map(to: a) map(alloc: b)
  #pragma omp target map(alloc: a, b)
  for (int i = 0; i < n; i++) b[i] = 2 * a[i] + 1;
  #pragma omp target exit data map(from: b) map(delete: a)
  int bad = 0;
  for (int i = 0; i < n; i++) bad += b[i] != 2 * i + 1;
  printf("bad= %d a_present= %d b_present= %d\n", bad,
         omp_target_is_present(a, d), omp_target_is_present(b, d));
  return 0;
}
