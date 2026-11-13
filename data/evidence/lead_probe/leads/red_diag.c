// lead 1: the assignment body with per-team diagnostics: each
// team's last iteration and the number of teams
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0;
  int last[1024], nt = 0;
  for (int t = 0; t < 1024; t++) last[t] = -1;
  #pragma omp target teams distribute reduction(max: l) map(tofrom: l, last, nt)
  for (int i = 1; i <= 64; i++) {
    l = (long long) i * 40;
    last[omp_get_team_num()] = i;
    if (omp_get_team_num() == 0) nt = omp_get_num_teams();
  }
  printf("l= %lld teams= %d lasts:", l, nt);
  for (int t = 0; t < nt && t < 1024; t++) printf(" %d", last[t]);
  printf("\n");
  return 0;
}
