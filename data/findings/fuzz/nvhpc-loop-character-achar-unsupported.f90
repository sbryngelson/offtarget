! # Finding (parity-fuzz-s1): NVHPC: a character value computed in the region (achar, a concatenation) assigned to a character
! # array element inside a loop construct of a target region fails to translate ("Character local variable unsupported on
! # device"); the same assignment in a distribute construct compiles and runs correctly
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: ice
! - observed: `NVFORTRAN-F-0155-Compiler failed to translate accelerator region (see -Minfo messages): Character local variable
!   unsupported on device (<tmpdir>/nvhpc`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `s= 1160` with `check=pass`
! - rule: "A loop construct specifies that the logical iterations of the associated loops may execute concurrently and permits
!   the encountering threads to execute the loop accordingly." (5.2 §11.7 p.257 l.8-9); the loop body is a character assignment,
!   which no restriction of the construct excludes
! - vendor: "The private, bind, and collapse clauses are supported" on the loop construct (NVIDIA HPC Compilers User's Guide
!   26.9, Using OpenMP, item 2.9.5; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt); the guide names no character limit
! - same-compiler control: controls/nvhpc-loop-character-distribute-control.f90 (one change from this file; correct on nvhpc
!   (NVHPC 25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.cl.jsonl, results/parity/nvs1/wt.cl.jsonl);
!   controls/nvhpc-loop-character-array-value-control.f90 (the value copied from a mapped character array instead of computed:
!   four edits from this file, the array, its initialization, its map clause and the assignment; correct on nvhpc (NVHPC 25.11),
!   nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.cl.jsonl, results/parity/nvs1/wt.cl.jsonl)
! - other families: afar (AFAR 24.3.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the file correctly (rows
!   results/parity/nvs1/tuo.cl.jsonl); cce19 (CCE 19.0.0) fail it another way, e.g. `ftn-7032 ftn: ERROR P, File =
!   ../../nvhpc-loop-character-achar-unsupported.f90, Line = 10`
! - variants: files next to the reduction in results/parity/nvs1/red/, rows results/parity/nvs1/wt.cl.jsonl (both releases,
!   separate and managed memory) and results/parity/nvs1/tuo.cl.jsonl: the seed's concatenation `achar(...) // xc(i)(2:4)` in a
!   loop construct of a target parallel region (nvhpc-loop-character-concatenation-target-parallel-variant.f90) fails the same
!   way; the same concatenation in a do construct of the target parallel region compiles
!   (nvhpc-loop-character-concatenation-do-control.f90) but its run does not end on either release, the implicit barrier of a
!   worksharing loop in a combined target parallel construct (the c1 finding nvhpc-target-parallel-single-hang.f90), so it is
!   not a control of this finding. A substring copy `o2(i)(2:4) = xc(i)(2:4)` in the loop construct compiles (exploration)
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvs1/gate_abd.cl.jsonl, results/parity/nvs1/gate_abd.cl.m2.jsonl, results/parity/nvs1/gate_c.cl.jsonl,
!   results/parity/nvs1/gate_c.cl.m2.jsonl, results/parity/nvs1/wt.cl.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2465893.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2476695.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3354124.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3482833.jsonl)
! - programs (1): par-s1-nvhpc-nvhpc269:2564
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its controls and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvs1/prerun.cl.txt); AFAR 24.3.0 and CCE 20/21/21.0.4
!   compile and run this file and its controls correctly with HSA_XNACK 0 and 1 (results/parity/nvs1/tuo.cl.jsonl); CCE 19
!   rejects character data in target regions ("Unsupported OpenMP construct Fortran character"), its own documented limit
!   (afar-cce19-character-defaultmap.f90). NVHPC is the compiler under test and is not counted as a witness
program p
  implicit none
  integer, parameter :: n = 16
  character(len=4) :: o2(n)
  integer :: i, s
  o2 = ' '
  !$omp target teams map(from: o2)
    !$omp loop
    do i = 1, n
      o2(i) = achar(64 + i)
    end do
    !$omp end loop
  !$omp end target teams
  s = 0
  do i = 1, n
    s = s + ichar(o2(i)(1:1))
  end do
  print '(a,i0)', 's= ', s
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', s == 16 * 64 + 136)
end program p

! site:
! title: character value in a loop construct: unsupported
! summary: nvfortran -mp=gpu appears not to support assigning a character value computed in the region (achar, a concatenation)
! + to a character array element inside a loop construct of a target region: the compile stops with "Character local variable
! + unsupported on device". The same assignment in a distribute construct, or the copy of a mapped character element in the loop
! + construct, compiles and runs correctly.
! control: fuzz/controls/nvhpc-loop-character-distribute-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-loop-character-array-value-control.f90 the value copied from a mapped character array (four
! + edits from the finding); correct on nvhpc, nvhpc269
! end site
