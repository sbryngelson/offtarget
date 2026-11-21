! # Finding (GCC 16.2): gfortran -O2 for amdgcn: int(a, 8) * int(b, 8) of two negative default integers is off by 2**32 in a target
!   region
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: wrong_answer (check=fail)
! - observed: `bad= 4` with `check=fail`; identical signature on 1 of 1 failing cells
! - expected: `bad= 0`, then `RESULT ran_on_host=0 check=pass`: the device computes the same 64-bit products as the host loop that
!   sets ref (each fits easily: |a|, |b| < 100), and r, mapped tofrom implicitly, is copied back
! - rule: r is copied back at the end of the region: "If the reference count of the corresponding list item is one or if the always
!   map-type-modifier is specified, and if the map-type is from or tofrom, the original list item is updated as if the list item
!   appeared in a from clause on a target update directive." (OpenMP 5.2 §5.8.3 p.154 l.2-5); INT(a, 8) converts a default integer
!   to integer(8) exactly and the product of two integer(8) values is exact here, so r(i) must equal ref(i)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-signed-widening-multiply-o2-wrong)
! - same-compiler control: controls/gcc-signed-widening-multiply-o2-wrong-direct-subscript-control.f90 (one change from this file;
!   correct on gcc (GCC 16.2.0); site rows, check case site-fuzz--gcc-signed-widening-multiply-o2-wrong)
! - legality: legal by reading: a target region with map(tofrom: hf), arrays a, b and r mapped implicitly, a sequential loop that
!   writes each r(i) once, so there is no data race; the subscript mod(i + 4, n) + 1 stays within 1..n. The rules witness
!   (offload.engine.prerun) accepts it, and other families' front ends compile and run it correctly (the rows)
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), b(n), i, hf, bad
  integer(8) :: r(n), ref(n)
  do i = 1, n
    a(i) = mod(i * 54 + 44, 101) - 50
    b(i) = mod(i * 53 + 27, 211) - 46
  end do
  do i = 1, n
    ref(i) = int(a(i), 8) * int(b(mod(i + 4, n) + 1), 8)
  end do
  r = 0
  hf = 1
  !$omp target map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      r(i) = int(a(i), 8) * int(b(mod(i + 4, n) + 1), 8)
    end do
  !$omp end target
  bad = count(r /= ref)
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', bad == 0)
end program p

! site:
! title: gfortran -O2: product of two widened negative integers off by 2**32 on AMD GPUs
! summary: GCC 16.2 at -O2 computes int(a, 8) * int(b, 8) wrongly in a target region on the MI300A when both operands are negative:
! + the result is the right product plus 2**32 (4 of 16 values). The same product with a direct subscript is right.
! control: fuzz/controls/gcc-signed-widening-multiply-o2-wrong-direct-subscript-control.f90 one change from the finding; correct on
! + gcc
! end site
