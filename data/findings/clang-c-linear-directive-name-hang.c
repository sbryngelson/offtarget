/* Finding (C): a directive-name modifier in a linear clause sends
   the clang front end into an endless loop.

   Legal OpenMP 6.0 C: linear(x: for, step(2)) names the directive the
   clause applies to (6.0 §5.4, p.174: "The directive-name-modifier is a
   universal modifier that can be used on any clause"; linear, 6.0
   §7.5.6, p.232). Expected: compiles
   (or, for a compiler without the 6.0 modifier, one diagnostic).

   Observed (2026-10-19): AFAR amdclang 24.0.0git and CCE craycc 19.0.0
   (the omp60-c-clause-linear-directive_name program: also 20.0.2 and
   21.0.3) print "error: expected expression" at the `for` twenty times,
   then "fatal error: too many errors emitted, stopping now", and do not
   exit: killed after 40 s with -fsyntax-only (the matrix: compile
   timeout on all four toolchains). Without `for,` it compiles at once.

   amdclang -fopenmp -fopenmp-version=60 -fsyntax-only
   craycc -fopenmp -fopenmp-version=60 -fsyntax-only */
int main(void) {
  int x = 0, b[8];
  #pragma omp parallel for linear(x: for, step(2))
  for (int i = 0; i < 8; i++) { b[i] = x; x += 2; }
  return b[1];
}
// site:
// title: craycc -fopenmp-version=60: linear(x: for, step(2)) sends the front end into an endless loop after "too many errors"
// control: ../vendor/checks/src/other/control/clang-c-linear-directive-name-hang-control.c linear(x: step(2)) without the
// + directive-name
// + modifier
// end site
