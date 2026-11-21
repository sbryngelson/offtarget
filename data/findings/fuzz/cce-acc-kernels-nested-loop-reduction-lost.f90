! # Finding (CCE): CCE ftn -h acc: in a kernels construct, a gang loop reduction over an inner independent loop reduction keeps only
!   one outer iteration's contribution
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes:
!   unified, copy; -O2
! - build: ftn -h acc -O2
! - failure: wrong_answer (check=fail)
! - observed: `s= 420 want= 2148` with `check=fail`; identical signature on 8 of 8 failing cells
! - expected: compiles and prints `s= 2148 want= 2148` with `check=pass`
! - rule: each loop's private copies are combined and "the result combined with the value of the original var and stored in the
!   original var" (OpenACC 3.4 §2.9.11 p.71 l.2551-2553), and "a reduction clause containing that variable must appear on each of
!   those loop directives" when the reduction spans nested loops with loop directives (l.2560-2562), as both do here; s, a scalar
!   with no data clause in a kernels construct, "will be treated as if it appears ... In a copy clause" (OpenACC 3.4 §2.6.2 p.41
!   l.1392-1393), so the host sees the sum
! - same-compiler control: controls/cce-acc-kernels-nested-loop-reduction-lost-delete-clause-independent-control.f90 (one change
!   from this file: no independent clause on the inner loop; correct on cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3),
!   cce21_4 (CCE 21.0.4); site rows, check case site-fuzz--cce-acc-kernels-nested-loop-reduction-lost)
! - other families: gcc (GCC 16.2.0) run the file correctly (site rows, check case
!   site-fuzz--cce-acc-kernels-nested-loop-reduction-lost)
! - legality: legal by reading: s is copied implicitly and reduced with the same operator on both loop directives; a is read only;
!   hf is written in one iteration and mapped by copy(hf); no other variable is shared and written, so there is no data race. The
!   rules witness with the race rule (offload.engine.prerun) and AMD flang's front end (-fopenacc) accept the file and its control
!   (offload.engine.prerun.check on Tuolumne, 2026-11-21); it was reduced from fuzz program acc1 seed 320 (generator fuzz-acc1),
!   whose sequential runs printed the model's checksum
! - releases: CCE 19.0.0, 20.0.2, 21.0.3 and 21.0.4 fail it the same way
program kred
  use openacc, only: acc_on_device, acc_device_host
  implicit none
  integer, parameter :: n = 3, m = 8
  integer :: a(n), i, j, s, want, hf
  do i = 1, n
    a(i) = i * 37 + 11
  end do
  want = 0
  do i = 1, n
    do j = 1, m
      want = want + a(i) + j
    end do
  end do
  s = 0
  hf = 0
  !$acc kernels copyin(a) copy(hf)
    !$acc loop gang reduction(+: s)
    do i = 1, n
      !$acc loop independent reduction(+: s)
      do j = 1, m
        if (i == 1 .and. j == 1) hf = merge(1, 0, acc_on_device(acc_device_host))
        s = s + a(i) + j
      end do
    end do
  !$acc end kernels
  print '(a,i0,a,i0)', 's= ', s, ' want= ', want
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', s == want)
end program kred

! site:
! title: CCE OpenACC: nested loop reduction in kernels loses contributions
! summary: CCE 19, 20 and 21 keep only one outer iteration's part of a sum reduced over a gang loop and an inner independent loop in
! + an OpenACC kernels construct; without independent on the inner loop the sum is right.
! control: fuzz/controls/cce-acc-kernels-nested-loop-reduction-lost-delete-clause-independent-control.f90 one change from the
! + finding; correct on cce19, cce20, cce21, cce21_4
! end site
