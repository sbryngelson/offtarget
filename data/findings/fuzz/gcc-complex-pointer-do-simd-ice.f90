! # Finding (GCC 16.2): gfortran -O2 for amdgcn: an internal compiler error in simplify_subreg for a do simd loop that assigns to a
!   complex(4) pointer array in a target region
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: ice
! - observed: `Please submit a full bug report, with preprocessed source (by using -freport-bug).`; identical signature on 1 of 1
!   failing cells
! - expected: compiles and prints `RESULT ran_on_host=0 check=pass`
! - rule: a worksharing-loop SIMD construct applies both constructs to the same loop: "Composite constructs combine constructs that
!   otherwise cannot be immediately nested. Specifically, composite constructs apply multiple loop-associated constructs to the same
!   canonical loop nest." (OpenMP 5.2 §17.5 p.343 l.25-27); a do simd orphaned in a target region binds to the region's
!   single-thread team, and an internal compiler error is never a conforming response to a conforming program
! - same-compiler control: controls/gcc-complex-pointer-do-simd-ice-shorten-do-simd-to-do-control.f90 (one change from this file;
!   correct on gcc (GCC 16.2.0); rows results/reduce/gcc-complex-pointer-do-simd-ice/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-complex-pointer-do-simd-ice)
! - legality: legal by reading: o1 is a complex(4) pointer associated with the target array o1t before the region and mapped tofrom
!   with hf; inside the target region a sequential loop over i contains an orphaned do simd over j that assigns o1(i, j) = i, each
!   element once, so there is no data race. The rules witness (offload.engine.prerun) accepts it, and other families' front ends
!   compile and run it correctly (the rows)
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 3, m = 2
  complex(4), pointer :: o1(:, :)
  complex(4), target :: o1t(n, m)
  integer :: i, j, hf
  o1 => o1t
  o1 = 0
  hf = 1
  !$omp target map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      !$omp do simd
      do j = 1, m
        o1(i, j) = i
      end do
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', all(o1(:, 1) == &
      & [(cmplx(i), i = 1, n)]))
end program p

! site:
! title: gfortran -O2: do simd on a complex pointer array in a target region crashes the compiler
! summary: GCC 16.2 stops with an internal compiler error in simplify_subreg (simplify-rtx.cc:8291) at -O2 for the amdgcn offload
! + target when an orphaned do simd loop in a target region assigns to a complex(4) pointer array; a plain do loop compiles.
! control: fuzz/controls/gcc-complex-pointer-do-simd-ice-shorten-do-simd-to-do-control.f90 one change from the finding; correct on
! + gcc
! end site
