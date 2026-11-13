#include <stdio.h>
#include <omp.h>
int main(void) {
  int nt = -1, host_flag = 1;
  #pragma omp target teams distribute parallel for map(from: nt, host_flag)
  for (int i = 1; i <= 64; i++) {
    if (i == 1) nt = omp_get_num_teams();
    if (i == 1) host_flag = (omp_is_initial_device() ? 1 : 0);
  }
  printf("nt=%d host_flag=%d\n", nt, host_flag);
  return 0;
}
