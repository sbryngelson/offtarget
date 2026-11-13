#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>
/* C port of the student's kernel. mode 0: direct element stores; 1: malloc/copy/free of a 12-byte temporary
   (what flang generates for the array constructor); 2: stack temporary copied with memcpy. */
#define M 439
#define N 329
#define P 329
#define BUFF 10
#define LAYERS 3
typedef struct {
  int loc[3]; double ip_loc[3]; int ip_grid[3]; double interp_coeffs[8]; int interp_valid; int ib_patch_id;
  double levelset; double levelset_norm[3]; int slip; int DB[3]; int xp, yp, zp;
} gp_t;
#define NJ (N + 1 + 2 * BUFF)
#define NK (P + 1 + 2 * BUFF)
#define IDX(i, j, k) ((((long)((i) + BUFF)) * NJ + ((j) + BUFF)) * NK + ((k) + BUFF))

int main(int argc, char **argv) {
  int spacing = atoi(argv[1]), nper = atoi(argv[2]), trials = atoi(argv[3]), mode = atoi(argv[4]);
  int cntmode = atoi(argv[5]), delay = atoi(argv[6]);
  long warm = argc > 7 ? atol(argv[7]) : 0;
  int *cnt = (int *)omp_target_alloc(sizeof(int), omp_get_default_device());
  size_t tot = (size_t)(M + 1 + 2 * BUFF) * NJ * NK;
  int *sf = calloc(tot, sizeof(int));
  int id = 0;
  for (int a = 0; a < nper; a++) for (int b = 0; b < nper; b++) for (int c = 0; c < nper; c++) {
    if (8 + a * spacing > M - 8 || 8 + b * spacing > N - 8 || 8 + c * spacing > P - 8) continue;
    id++;
    for (int k = -4; k <= 4; k++) for (int j = -4; j <= 4; j++) for (int i = -4; i <= 4; i++)
      if (i * i + j * j + k * k <= 16) sf[IDX(8 + a * spacing + i, 8 + b * spacing + j, 8 + c * spacing + k)] = id;
  }
  long num_gps = 0;
  for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++) {
    if (!sf[IDX(i, j, k)]) continue;
    int g = 0;
    for (int ii = i - LAYERS; ii <= i + LAYERS && !g; ii++) for (int jj = j - LAYERS; jj <= j + LAYERS && !g; jj++)
      for (int kk = k - LAYERS; kk <= k + LAYERS; kk++) if (!sf[IDX(ii, jj, kk)]) { g = 1; break; }
    num_gps += g;
  }
  gp_t *gps = malloc(num_gps * sizeof(gp_t));
  int *hits = malloc((size_t)(M + 1) * (N + 1) * (P + 1) * sizeof(int));
#pragma omp target enter data map(to : sf[0 : tot]) map(alloc : gps[0 : num_gps])
  printf("spheres %d  ghost cells %ld  mode %d cntmode %d delay %d\n", id, num_gps, mode, cntmode, delay);
  if (warm > 0) {
    long wb = 0;
#pragma omp target teams distribute parallel for reduction(+ : wb)
    for (long w = 0; w < warm; w++) {
      int *p = (int *)malloc(3 * sizeof(int));
      if (!p) { wb++; continue; }
      p[0] = (int)w; p[1] = 1; p[2] = 2;
      if (p[0] != (int)w) wb++;
      free(p);
    }
    printf("warm-up kernel: bad %ld\n", wb);
  }
  for (int t = 1; t <= trials; t++) {
    int count = 0;
if (cntmode == 0) {
#pragma omp target teams distribute parallel for collapse(3) map(to : count)
    for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++) {
      if (sf[IDX(i, j, k)] != 0) {
        int is_gp = 0;
        for (int ii = i - LAYERS; ii <= i + LAYERS && !is_gp; ii++)
          for (int jj = j - LAYERS; jj <= j + LAYERS && !is_gp; jj++)
            for (int kk = k - LAYERS; kk <= k + LAYERS; kk++)
              if (sf[IDX(ii, jj, kk)] == 0) { is_gp = 1; break; }
        if (is_gp) {
          int li;
#pragma omp atomic capture
          li = count++;
          if (mode == 0) { gps[li].loc[0] = i; gps[li].loc[1] = j; gps[li].loc[2] = k; }
          else if (mode == 3) { volatile int sd = 0; for (int d = 0; d < delay; d++) sd += d; gps[li].loc[0] = i; gps[li].loc[1] = j; gps[li].loc[2] = k; }
          else if (mode == 1) {
            int *tmp = (int *)malloc(3 * sizeof(int));
            tmp[0] = i; tmp[1] = j; tmp[2] = k;
            memcpy(gps[li].loc, tmp, 3 * sizeof(int));
            free(tmp);
          } else { int tmp[3]; tmp[0] = i; tmp[1] = j; tmp[2] = k; memcpy(gps[li].loc, tmp, 3 * sizeof(int)); }
          gps[li].ib_patch_id = sf[IDX(i, j, k)];
          gps[li].xp = 0; gps[li].yp = 0; gps[li].zp = 0; gps[li].slip = 0;
          gps[li].DB[0] = 0; gps[li].DB[1] = 0; gps[li].DB[2] = 0;
        }
      }
    }
  } else {
#pragma omp target is_device_ptr(cnt)
    *cnt = 0;
#pragma omp target teams distribute parallel for collapse(3) is_device_ptr(cnt)
    for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++) {
      if (sf[IDX(i, j, k)] != 0) {
        int is_gp = 0;
        for (int ii = i - LAYERS; ii <= i + LAYERS && !is_gp; ii++)
          for (int jj = j - LAYERS; jj <= j + LAYERS && !is_gp; jj++)
            for (int kk = k - LAYERS; kk <= k + LAYERS; kk++)
              if (sf[IDX(ii, jj, kk)] == 0) { is_gp = 1; break; }
        if (is_gp) {
          int li;
#pragma omp atomic capture
          li = (*cnt)++;
          if (mode == 0) { gps[li].loc[0] = i; gps[li].loc[1] = j; gps[li].loc[2] = k; }
          else if (mode == 3) { volatile int sd = 0; for (int d = 0; d < delay; d++) sd += d; gps[li].loc[0] = i; gps[li].loc[1] = j; gps[li].loc[2] = k; }
          else if (mode == 1) {
            int *tmp = (int *)malloc(3 * sizeof(int));
            tmp[0] = i; tmp[1] = j; tmp[2] = k;
            memcpy(gps[li].loc, tmp, 3 * sizeof(int));
            free(tmp);
          } else { int tmp[3]; tmp[0] = i; tmp[1] = j; tmp[2] = k; memcpy(gps[li].loc, tmp, 3 * sizeof(int)); }
          gps[li].ib_patch_id = sf[IDX(i, j, k)];
          gps[li].xp = 0; gps[li].yp = 0; gps[li].zp = 0; gps[li].slip = 0;
          gps[li].DB[0] = 0; gps[li].DB[1] = 0; gps[li].DB[2] = 0;
        }
      }
    }
  }
#pragma omp target update from(gps[0 : num_gps])
    memset(hits, 0, (size_t)(M + 1) * (N + 1) * (P + 1) * sizeof(int));
    long bad = 0, dup = 0, missing = 0;
    for (long q = 0; q < num_gps; q++) {
      int *l = gps[q].loc;
      if (l[0] < 0 || l[1] < 0 || l[2] < 0 || l[0] > M || l[1] > N || l[2] > P) { bad++; continue; }
      hits[((long)l[0] * (N + 1) + l[1]) * (P + 1) + l[2]]++;
      if (sf[IDX(l[0], l[1], l[2])] != gps[q].ib_patch_id) bad++;
    }
    long covered = 0;
    for (long q = 0; q < (long)(M + 1) * (N + 1) * (P + 1); q++) { if (hits[q] > 1) dup++; if (hits[q] > 0) covered++; }
    missing = num_gps - covered;
    printf("trial %2d: bad records %ld  duplicated cells %ld  missing cells %ld\n", t, bad, dup, missing);
  }
  return 0;
}
