! # Finding (GCC 16.2, application corpus): OpenACC tile(32, 32) over loops whose trip counts are not multiples of 32 computes
!   wrong elements
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
!   separate memory only; -O2
! - build: gfortran -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: wrong_answer
! - observed: `bad= 4342` (of the 10000 elements checked) and check=fail in every run (gcc_sm80: mandatory wrong 5 of 5; unset wrong
!   5 of 5; gcc_g90: mandatory wrong 5 of 5; unset wrong 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl))
! - expected: `bad= 0`, then `RESULT ran_on_host=0 check=pass`
! - rule: "Each loop in the nest will be split, or strip-mined, into two loops, an outer tile loop and an inner element loop. The
!   trip count of the element loop will be limited to the corresponding tile size from the size-expr-list" (OpenACC 3.4 §2.9.8
!   l.2486-2489): tiling reorders the iterations of the nest, each still runs once. The tile clause is OpenACC 2.0's; GCC documents
!   OpenACC 2.6.
! - same-compiler control (correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5; unset pass 5
!   of 5 (results/parity/<machine>/<tc>/probes.jsonl)): collapse(2) in place of tile(32, 32) (controls/gcc-acc-tile-control.f90).
!   With trip counts of 64 (multiples of the tile size) the tiled form is correct too, and so is a one-loop tile(32) (C and Fortran,
!   both GPUs, mandatory pass 5 of 5, unset pass 5 of 5; results/parity/probes-r2/tile_mult32.*, tile_one_loop.*).
! - application: prk-f-stencil-acc (FORTRAN/stencil-openacc.F90) of the Parallel Research Kernels
!   (data/bench/apps/manifest.yaml): its
!   stencil kernels are `acc parallel loop tile(*,*)` over the interior of a 1000 x 1000 grid; GCC's run prints `ERROR: L1 norm =
!   22.634350 Reference L1 norm = 22.000000` on both GPUs (results/parity/<machine>/results/apps/runs). NVHPC 25.11 and 26.9
!   validate it (results/apps/wingtip/runs).
! - other families: NVHPC 25.11 and 26.9 run this file correctly in both memory modes, CCE 19/20/21/21.0.4 too (Fortran OpenACC)
!   (site matrix). The site's finding matrix runs this file on every compiler.
! - legality: OpenACC 3.4 §2.9.8; the nest is tightly nested and every iteration writes its own element (no race). GCC is a compiler
!   under test only and never a legality witness.
program tile_partial
  use openacc, only: acc_device_host, acc_on_device
  implicit none
  integer, parameter :: n = 100
  integer :: a(n, n)
  integer :: i, j, bad, want, host_flag
  a = 0
  !$acc parallel loop tile(32, 32) copy(a)
  do j = 2, n - 1
    do i = 2, n - 1
      a(i, j) = a(i, j) + i + j
    end do
  end do
  host_flag = 1
  !$acc parallel num_gangs(1) copy(host_flag)
  if (.not. acc_on_device(acc_device_host)) host_flag = 0
  !$acc end parallel
  bad = 0
  do j = 1, n
    do i = 1, n
      want = 0
      if (i > 1 .and. i < n .and. j > 1 .and. j < n) want = i + j
      if (a(i, j) /= want) bad = bad + 1
    end do
  end do
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program tile_partial
! site:
! title: OpenACC tile(32, 32) over loops whose trip counts are not multiples of the tile size computes wrong elements
! summary: A parallel loop tile(32, 32) over a 98 x 98 (or 100 x 100) nest should run every iteration once. GCC 16.2 leaves 4342 of
! + the 10000 elements it checks wrong (C and Fortran), on the MI250X and the A100. The same nest with collapse(2), or with trip
! + counts that are multiples of 32, is correct. Found through the Parallel Research Kernels' OpenACC stencil.
! control: apps/controls/gcc-acc-tile-control.f90 collapse(2) in place of tile(32, 32)
! same_as: apps/gcc-acc-c-tile-partial-tiles-wrong
! end site
