! # Finding (from the data/bench/fresh draft fresh-022): CCE 19/20 abort on a list-directed
!   PRINT in a target region in copy mode
!
! - source: data/bench/fresh/fresh-022.f90 (llvm-project issue 166338, the reporter's program unchanged)
! - compilers: CCE 19.0.0 and 20.0.2 ftn, -fopenmp -O2, OMP_TARGET_OFFLOAD=mandatory; MI300A (gfx942)
!   at HSA_XNACK=0 and MI250X (gfx90a, Tioga) at HSA_XNACK=0
! - expected: "Hello, world!" from the device. PRINT is a base-language statement; OpenMP 5.2 places
!   no restriction on I/O statements in a target region (the restrictions on structured blocks,
!   §4.3 p.76-77, concern branches into and out of the block), and an implementation is compliant
!   only if it "compiles and executes all other conforming programs" (§1.6 p.34 l.22-24). HPE
!   documents the case: "Fortran PRINT
!   statements are supported, with limitations, when called from OpenMP offload regions compiled for
!   AMD GPU targets. The current implementation supports PRINT statements with a single scalar value
!   of type character, integer, real, or complex" (intro_openmp(7), CCE 19.0.0 and 20.0.2,
!   "Printing from GPU kernels"; data/index/claims/)
! - actual: CCE 19 and 20 at HSA_XNACK=0: "Memory access fault by GPU node-4 ... Reason: Unknown",
!   SIGABRT, nothing printed (MI300A three runs each; MI250X). At HSA_XNACK=1 correct. The same with
!   `print *, 42` (data/reports/fresh-drafts/d022-list-int.f90) and with two list-directed PRINTs
!   (d022-two-lists.f90)
! - control (same compiler): the formatted `print '(a)', "Hello, world!"`
!   (data/reports/fresh-drafts/d022-fmt-literal.f90) prints the line on CCE 19/20 at XNACK 0 and 1.
!   With a mapped scalar written in the same region the list-directed PRINT also works
!   (d022-map-only.f90, d022-list-literal-dev.f90): the abort needs a region without other data
! - other families: AFAR, CCE 21.0.3 and NVHPC 25.11/26.9 (A100, separate and managed memory) print
!   the line
! - legality: legal by reading (no OpenMP construct but target; no data)
! - evidence: results/fresh-drafts/tuo*-*.jsonl, tioga/tioga-a.jsonl, wingtip/nv.jsonl (runs of the review);
!   the data/bench/fresh ground truth (data/bench/fresh/outcomes.csv: cce19/cce20
!   copy crash on gfx942 and gfx90a)
program reproducer
  implicit none
  !$omp target
  print *, "Hello, world!"
  !$omp end target
end program reproducer
! site:
! title: ftn: a list-directed PRINT in a target region aborts the run in copy mode
! control: ../vendor/checks/src/cce/control/cce-list-directed-print-in-target-copy-crash-control.f90 a formatted PRINT, print '(a)',
! + instead of list-directed print *
! end site
