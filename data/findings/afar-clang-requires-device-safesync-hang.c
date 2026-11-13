/* Finding (C): AFAR amdclang hangs on requires device_safesync.

   Legal OpenMP 6.0 C (6.0 §10.5.1.7: device_safesync is a requires
   clause; without an argument it means device_safesync(true)).

   Observed (2026-10-19): amdclang (AFAR 24.0.0git, drop 24.3.0) does not
   finish on this file: killed after 90 s with
   `-fopenmp -fopenmp-version=60 --offload-arch=gfx942 -c`, after 300 s
   with `-fopenmp -fopenmp-version=60 -fsyntax-only`, and after 30 s with
   `-fopenmp-version=52 -fsyntax-only` (where the clause is unknown and
   should be diagnosed). The omp60-c-clause-device_safesync programs time
   out in compilation. CCE craycc 19.0.0, 20.0.2 and 21.0.3 stop at once:
   "warning: extra tokens at the end of '#pragma omp requires' are
   ignored" and "error: expected at least one clause on '#pragma omp
   requires' directive" (the clause is unknown to them). AFAR amdflang
   compiles and runs the Fortran form (`!$omp requires device_safesync`;
   omp60-clause-device_safesync: unobservable). */
#pragma omp requires device_safesync
int main(void) { return 0; }
// site:
// title: amdclang -fopenmp-version=60: compile does not finish on #pragma omp requires device_safesync
// control: ../vendor/checks/src/afar/control/afar-clang-requires-device-safesync-hang-control.c another requires clause,
// + atomic_default_mem_order(seq_cst)
// end site
