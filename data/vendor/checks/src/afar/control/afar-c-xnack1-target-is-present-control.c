#include <stdio.h>
#include <omp.h>
int main(void) {
  int a[64], d = omp_get_default_device();
  for (int i = 0; i < 64; i++) a[i] = 1;
  #pragma omp target enter data map(to: a)
  printf("after enter data: present= %d\n", omp_target_is_present(a, d));
  #pragma omp target exit data map(release: a)
  printf("after exit data: present= %d\n", omp_target_is_present(a, d));
  return 0;
}
