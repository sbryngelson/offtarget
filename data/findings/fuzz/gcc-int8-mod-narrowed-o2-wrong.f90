! # Finding (GCC 16.2): gfortran -O2 for amdgcn: mod(x, k) of an integer(8) x assigned to a default integer is wrong in a target
!   region
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: wrong_answer (check=fail)
! - observed: `bad= 56` with `check=fail`; identical signature on 1 of 1 failing cells
! - expected: `bad= 0`, then `RESULT ran_on_host=0 check=pass`: the device assigns the same mod(x(i), 1000003_8) to r(i) as the host
!   loop does to ref(i) (each value is below 1000003, so the conversion to default integer is exact), and r, mapped tofrom
!   implicitly, is copied back
! - rule: r is copied back at the end of the region: "If the reference count of the corresponding list item is one or if the always
!   map-type-modifier is specified, and if the map-type is from or tofrom, the original list item is updated as if the list item
!   appeared in a from clause on a target update directive." (OpenMP 5.2 §5.8.3 p.154 l.2-5); x and r are arrays referenced in the
!   region, so they are mapped tofrom implicitly, and MOD and the intrinsic assignment to a default integer are evaluated the same
!   way on the device, so r(i) must equal ref(i)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-int8-mod-narrowed-o2-wrong)
! - same-compiler control: controls/gcc-int8-mod-narrowed-o2-wrong-integer8-result-control.f90 (one change from this file; correct
!   on gcc (GCC 16.2.0); site rows, check case site-fuzz--gcc-int8-mod-narrowed-o2-wrong)
! - legality: legal by reading: a target region with map(tofrom: hf), arrays x and r mapped implicitly, a sequential loop and no
!   data race; MOD of two integer(8) values assigned to a default integer whose value fits (each is below 1000003). The rules
!   witness (offload.engine.prerun) accepts it, and other families' front ends compile and run it correctly (the rows)
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer(8) :: x(n)
  integer :: r(n), ref(n)
  integer :: i, hf, bad
  do i = 1, n
    x(i) = int(i, 8) * 1000000007_8 + 12_8
    ref(i) = mod(x(i), 1000003_8)
  end do
  r = 0
  hf = 1
  !$omp target map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      r(i) = mod(x(i), 1000003_8)
    end do
  !$omp end target
  bad = count(r /= ref)
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', bad == 0)
end program p

! site:
! title: gfortran -O2: 64-bit integer MOD narrowed to default integer is wrong on AMD GPUs
! summary: GCC 16.2 at -O2 computes mod(x, 1000003_8) of an integer(8) x assigned to a default integer wrongly in a target region on
! + the MI300A (56 of 64 values); with an integer(8) result the values are right.
! control: fuzz/controls/gcc-int8-mod-narrowed-o2-wrong-integer8-result-control.f90 one change from the finding; correct on gcc
! end site
