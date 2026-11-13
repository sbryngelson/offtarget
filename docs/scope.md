# What offload can and cannot do

`offload` is a lookup over a catalog of measured compiler behaviour. It does not run, compile or analyse your program
beyond reading its directives. This page says what that lets it do and what it cannot do.

## What it does

- **`can-use`** shows, for one clause, directive or construct, what happened when the catalog program for it ran on
  each compiler, machine and memory mode. The result is `correct`, `unsupported` or `unknown`.
- **`issues`** searches the known problems. There are over 300, about three quarters in Fortran and the rest in C.
  Each has a small legal reproducer, the spec section and the measurements per compiler. Its status is open, fixed,
  changed, not-reproduced or mixed.

The tool works offline, needs no compiler or GPU, and gives the same answers on the command line and on the website.

## What it covers

| | covered |
|---|---|
| compilers in `can-use` | AFAR 24.3.0, CCE 19.0.0, 20.0.2, 21.0.3 (and 21.0.4 in the tables), NVHPC 25.11 and 26.9 |
| compilers in `issues` only | GCC 16.2 (offloading to MI300A, MI250X, MI300X, MI350X and A100) |
| machines and modes | MI300A (unified and copy memory), MI250X (copy), A100 (separate and managed memory) |
| languages | Fortran and C; OpenMP 5.0 to 6.0 (5.2 by default) and OpenACC 3.4 |
| scope | code that runs on the device, and host code that feeds a target region |

## What it does not do

- **It cannot show that a program is correct or legal.** If it reports nothing, no catalog program matches yours. That
  does not mean your program works. A match means a catalog program with the same construct failed. Your own
  combination of clauses, data and flags may behave differently.
- **It knows only what was measured.** Other compilers (LLVM clang, Intel and others), other releases, other GPUs and
  other flags are not covered. A fix in a newer release stays unknown until the catalog is rerun. Each `issues` entry
  shows the versions it was measured on.
- **It does not read C++**, fixed-form Fortran or CUDA. Other files are reported as not read.
- **It does not check performance, numerics beyond the test's expected output, or host-only code.**
- **Results depend on the measurement setup.** That includes the optimisation level, the environment (for example
  `HSA_XNACK`) and the compiler flags recorded in each finding. A different setup can behave differently.
- **A finding does not say who is at fault.** The reproducers are legal by the spec text as read when they were
  written, and a vendor may read the spec differently. A finding reports observed behaviour and gives the evidence.

## Reading a result

| you see | it means |
|---|---|
| `unknown` in `can-use` | the run did not settle it (for example the program ran on the host) |
