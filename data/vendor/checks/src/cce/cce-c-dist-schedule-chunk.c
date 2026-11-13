#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n];
  int b[n];
  int ref[n];
  int host_flag;
  bool ok;
  int team[n];
  int nt;
  bool dok;
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
  for (int k1_ = 0; k1_ < n; k1_++)
    team[k1_] = -1;
  nt = -1;
  #pragma omp target teams distribute parallel for map(to: a) map(from: b) map(from: team, nt) \
      map(tofrom: host_flag) default(none) shared(a, b, team, nt, host_flag) num_teams(4) \
      dist_schedule(static, 4)
  for (int i = 1; i <= n; i++) {
    b[i - 1] = 2 * a[i - 1] + 1;
    team[i - 1] = omp_get_team_num();
    if (i == 1) nt = omp_get_num_teams();
    if (i == 1) host_flag = (omp_is_initial_device() ? 1 : 0);
  }
  dok = true;
  for (int i = 1; i <= n; i++) {
    dok = dok && (team[i - 1] == ((i - 1) / 4 % nt));
  }
  bool t2_ = true;
  for (int k3_ = 0; k3_ < n; k3_++)
    t2_ = t2_ && (b[k3_] == ref[k3_]);
  ok = t2_ && (nt >= 1) && dok;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
