#include <stdio.h>
enum { n = 64 };
int main(void) {
  int a[n], b[n], k, bad = 0;
  for (int i = 0; i < n; i++) { a[i] = i; b[i] = 0; }
  #pragma omp target enter data map(to: a) map(alloc: b)
  for (int i = 0; i < n; i++) a[i] += 10;
  #pragma omp target update to(a[0:n])
  #pragma omp target map(alloc: a, b)
  for (int i = 0; i < n; i++) b[i] = a[i];
  #pragma omp target update from(b)
  #pragma omp target exit data map(release: a, b)
  for (int i = 0; i < n; i++) bad += b[i] != i + 10;
  printf("to iterator: bad= %d\n", bad);
  return 0;
}
