#include <stdio.h>
#include <omp.h>
int main(void) {
  int team[64], nt = -1;
  #pragma omp target teams distribute parallel for map(from: team, nt) num_teams(4) dist_schedule(static, 4)
  for (int i = 0; i < 64; i++) { team[i] = omp_get_team_num(); if (i == 0) nt = omp_get_num_teams(); }
  printf("nt=%d team:", nt); for (int i = 0; i < 64; i++) printf(" %d", team[i]); printf("\n");
  return 0;
}
