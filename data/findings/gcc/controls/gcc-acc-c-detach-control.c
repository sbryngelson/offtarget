#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>

enum { n = 64 };
struct holder {
  int *v;
};

int main(void) {
  int b[n];
  int host_flag = 1, sum = 0;
  struct holder h;
  h.v = malloc(n * sizeof(int));
  for (int i = 0; i < n; i++) {
    h.v[i] = 1;
    b[i] = 0;
  }
  #pragma acc enter data copyin(h)
  #pragma acc enter data copyin(h.v[0:n])
  #pragma acc parallel loop copyout(b) copy(host_flag) present(h)
  for (int i = 0; i < n; i++) {
    if (i == 0) host_flag = acc_on_device(acc_device_host) ? 1 : 0;
    b[i] = i + 1 + h.v[i];
  }
  #pragma acc exit data delete(h.v[0:n])
  #pragma acc exit data delete(h)
  for (int i = 0; i < n; i++)
    sum += b[i];
  free(h.v);
  printf("sum= %d\n", sum);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, sum == 2144 ? "pass" : "fail");
  return 0;
}
