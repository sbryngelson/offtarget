#include <omp.h>
#include <stdio.h>
#define N 100000
int main(void) {
  static double a[N];
  double sum = 0.0;
  int on_host = 1, nteams = 0;
  for (int i = 0; i < N; i++) a[i] = i * 0.5;
#pragma omp target teams distribute parallel for reduction(+:sum) map(to:a) map(tofrom:on_host, nteams)
  for (int i = 0; i < N; i++) {
    if (i == 0) { on_host = omp_is_initial_device(); nteams = omp_get_num_teams(); }
    sum += a[i];
  }
  double want = 0.5 * (double)N * (N - 1) / 2.0;
  printf("teams.c sum=%.1f want=%.1f on_host=%d nteams=%d %s\n", sum, want,
         on_host, nteams, (sum == want && !on_host) ? "PASS" : "FAIL");
  return !(sum == want && !on_host);
}
