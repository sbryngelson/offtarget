// NVHPC 25.11 and 26.9 (nvc), NVIDIA A100 80GB PCIe
// (wingtip, sm_80). nvc rejects the OpenACC atomic update x = x + v + 1
// ("NVC++-S-0155-Invalid atomic update expression") and then stops with an
// internal compiler error ("NVC++-F-0000-Internal compiler error. invalid ILM
// atomic region"), at -O0 and -O2, for -acc=gpu and -acc=multicore.
// Spec: one C form of an atomic update is "x = x binop expr", and "The
// expression x binop expr must be mathematically equivalent to x binop
// (expr). This requirement is satisfied if the operators in expr have
// precedence greater than binop, or by using parentheses around expr or
// subexpressions of expr" (OpenACC 3.4 §2.12, p.77-78). C parses the
// statement as (x + v) + 1, which is x + (v + 1) for int: the precedence and
// parentheses forms are sufficient, not necessary, so the statement is a
// legal update. The same update written x = x + (v + 1) or x += v + 1
// compiles and gives 2080.
// Fortran: nvfortran fails the same form the same way and, in a gang loop,
// its front end crashes (nvhpc-acc-atomic-update-sum-fort2-crash.f90).
// Expected: "x=2080" (a diagnostic would at least not be an internal error).
// Observed (2026-10-24, rerun 2026-10-25, nvc 25.11-0 and 26.9-0, the flags
// below, -O0 and -acc=multicore): compile exit status 2 with the two
// messages above, on both releases; the two other spellings print x=2080
// (log: data/evidence/acc_c_probe/atomic/run.log, sum.c, sum_paren.c,
// sum_compound.c).
// Found by the catalog: the C port of acc34-clause-gang, acc34-clause-gang-dim
// and acc34-directive-loop writes b[i - 1] = b[i - 1] + 2 * a[i - 1] + 1
// (the -binop programs: acc34-c-clause-gang-binop, acc34-c-clause-gang-dim-
// binop, acc34-c-directive-loop-binop); reduced by hand.
// NVHPC: nvc -acc=gpu -gpu=cc80 -gpu=mem:separate -O2
#include <stdio.h>
int main(void) {
  int x = 0;
  #pragma acc parallel loop copy(x)
  for (int v = 0; v < 64; v++) {
    #pragma acc atomic update
    x = x + v + 1;
  }
  printf("x=%d\n", x);
  return 0;
}
// site:
// title: nvc/nvfortran -acc: atomic update x = x + v + 1 rejected, then internal compiler error (nvc) or fort2 crash (nvfortran)
// control: ../vendor/checks/src/nvhpc/control/nvhpc-c-acc-atomic-update-sum-ice-control.c x = x + (v + 1), the right-hand side in
// + parentheses
// end site
