! # Finding (parity-fuzz-s1): NVHPC 25.11: an assumed-length character dummy argument in a map clause of a target region stops
! # the compile with an internal compiler error ("size_of: attempt to size assumed size character"); with an explicit length it
! # compiles and runs correctly, and 26.9 compiles both
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: rejected
! - observed: `NVFORTRAN-S-0000-Internal compiler error. size_of: attempt to size assumed size character       0
!   (<tmpdir>/nvhpc-assumed-length-character-dummy-map-`; identical signature on 2 of 2 failing cells
! - expected: compiles and prints `r= 78` with `check=pass`
! - rule: "The map clause specifies how an original list item is mapped from the current task's data environment to a
!   corresponding list item in the device data environment" (5.2 §5.8.3 p.151 l.8-9): an assumed-length character dummy is a
!   character scalar variable whose length is that of the actual argument, a list item like any other scalar
! - vendor: "The map clause is supported as described in 2.19.7" on the target construct (NVIDIA HPC Compilers User's Guide
!   26.9, Using OpenMP, item 2.12.5; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - same-compiler control: controls/nvhpc-explicit-length-character-dummy-control.f90 (one change from this file; correct on nvhpc
!   (NVHPC 25.11); rows results/parity/nvs1/tuo.ch.jsonl, results/parity/nvs1/wt.ch.jsonl)
! - other families: afar (AFAR 24.3.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the file correctly
!   (rows results/parity/nvs1/tuo.ch.jsonl); cce19 (CCE 19.0.0) fail it another way, e.g. `ftn-7032 ftn: ERROR KP1, File =
!   ../../nvhpc-assumed-length-character-dummy-map-ice.f90, Line = 15`
! - variants: files next to the reduction in results/parity/nvs1/red/, rows results/parity/nvs1/wt.ch.jsonl (both releases,
!   separate and managed memory) and results/parity/nvs1/tuo.ch.jsonl: the dummy mapped implicitly
!   (nvhpc-assumed-length-character-dummy-implicit-variant.f90) fails the same way on 25.11 and is correct on 26.9; NVHPC 26.9
!   compiles and runs this file correctly in both memory modes (results/parity/nvs1/wt.ch.jsonl and the gate rows), the same
!   family, not a witness. The s1 program 8930 fails on 26.9 at run time ("Present table errors" at the same dummy): with the
!   dummy given an explicit length the whole seed runs with the expected checksum on both releases (exploration), but no small
!   program reproduced the 26.9 failure
! - gate and confirmer: 2 of 2 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvs1/gate_abd.ch.jsonl, results/parity/nvs1/gate_abd.ch.m2.jsonl, results/parity/nvs1/gate_c.ch.jsonl,
!   results/parity/nvs1/gate_c.ch.m2.jsonl, results/parity/nvs1/wt.ch.jsonl); campaign gate of the programs below: 1 cells, 1
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2476695.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3482833.jsonl)
! - programs (1): par-s1-nvhpc-nvhpc269:8930; seed 8781 on 25.11 carries the same ICE message in its cell's stderr behind a
!   first diagnostic of SIMDLEN not implemented (a character(len=*) dummy in map(always, tofrom:)), so it is not counted; on
!   26.9 that seed runs with a wrong checksum
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its control and the variant above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvs1/prerun.ch.txt); AFAR 24.3.0 and CCE 20/21/21.0.4
!   compile and run all of them correctly with HSA_XNACK 0 and 1 (results/parity/nvs1/tuo.ch.jsonl); CCE 19 rejects character
!   data in target regions ("Unsupported OpenMP construct Fortran character"), its own documented limit
!   (afar-cce19-character-defaultmap.f90). NVHPC 26.9 compiles and runs this file correctly but is not counted as a witness:
!   NVHPC is the compiler under test
program p
  implicit none
  integer :: r
  character(len=8) :: xs
  xs = 'NnLXCqNL'
  r = 0
  call kp1(xs, r)
  print '(a,i0)', 'r= ', r
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', r == ichar('N'))
contains
  subroutine kp1(xs, r)
    character(len=*), intent(in) :: xs
    integer, intent(inout) :: r
    !$omp target map(to: xs) map(tofrom: r)
    r = ichar(xs(1:1))
    !$omp end target
  end subroutine kp1
end program p

! site:
! title: assumed-length character dummy in a map clause: ICE
! summary: nvfortran 25.11 -mp=gpu appears to behave incorrectly on an assumed-length character dummy argument
! + (character(len=*)) named in a map clause of a target region, or mapped implicitly: the compile stops with the internal
! + compiler error "size_of: attempt to size assumed size character". With an explicit length it compiles and runs correctly;
! + 26.9 compiles and runs both.
! control: fuzz/controls/nvhpc-explicit-length-character-dummy-control.f90 one change from the finding; correct on nvhpc
! end site
