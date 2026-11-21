! # Finding (CCE): CCE ftn -h acc 19 and 20: a sum reduced both on a parallel construct and on its gang loop comes back as the
!   original value (0)
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2); modes: unified, copy; -O2
! - build: ftn -h acc -O2
! - failure: wrong_answer (check=fail)
! - observed: `s= 0 want= 156` with `check=fail`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `s= 156 want= 156` with `check=pass`
! - rule: the reduction clause on the parallel construct makes a private copy per gang and "At the end of the region, the values for
!   each gang are combined using the reduction operator, and the result combined with the value of the original var and stored in
!   the original var." (OpenACC 3.4 §2.5.15 p.39 l.1294-1296); the loop's reduction combines its private copies "and the result
!   combined with the value of the original var and stored in the original var" (OpenACC 3.4 §2.9.11 p.71 l.2551-2553); "The
!   reduction result is available after the region." (§2.5.15 l.1300-1301)
! - same-compiler control: controls/cce-acc-parallel-and-gang-loop-reduction-lost-copy-not-reduction-control.f90 (one change from
!   this file: copy(s) for reduction(+: s) on the parallel construct; correct on cce19 (CCE 19.0.0), cce20 (CCE 20.0.2); site rows,
!   check case site-fuzz--cce-acc-parallel-and-gang-loop-reduction-lost)
! - other families: cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), gcc (GCC 16.2.0) run the file correctly (site rows, check case
!   site-fuzz--cce-acc-parallel-and-gang-loop-reduction-lost)
! - legality: legal by reading: s is reduced with the same operator on the parallel construct and its gang loop (which also
!   satisfies OpenACC 3.4 §2.6.2's restriction that a loop reduction under a parallel construct has a data, private or reduction
!   clause there); the inner loop has no directive and runs sequentially in each iteration; a is read only and hf is written once
!   and mapped by copy(hf), so there is no data race. The rules witness with the race rule (offload.engine.prerun) and AMD flang's
!   front end (-fopenacc) accept the file and its control (offload.engine.prerun.check on Tuolumne, 2026-11-21); it represents the
!   fuzz programs of acc1 that CCE 19 and 20 fail and CCE 21 runs correctly (seed 188, generator fuzz-acc1)
! - releases: CCE 19.0.0 and 20.0.2 fail it the same way; CCE 21.0.3 and 21.0.4 run it correctly
program pred
  use openacc, only: acc_on_device, acc_device_host
  implicit none
  integer, parameter :: n = 3, m = 8
  integer :: a(n), i, j, s, want, hf
  do i = 1, n
    a(i) = i
  end do
  want = 0
  do i = 1, n
    do j = 1, m
      want = want + a(i) + j
    end do
  end do
  s = 0
  hf = 0
  !$acc parallel copyin(a) copy(hf) reduction(+: s)
    !$acc loop gang reduction(+: s)
    do i = 1, n
      do j = 1, m
        if (i == 1 .and. j == 1) hf = merge(1, 0, acc_on_device(acc_device_host))
        s = s + a(i) + j
      end do
    end do
  !$acc end parallel
  print '(a,i0,a,i0)', 's= ', s, ' want= ', want
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', s == want)
end program pred

! site:
! title: CCE 19/20 OpenACC: parallel plus gang loop reduction returns 0
! summary: CCE 19 and 20 return the original value of a variable reduced both on an OpenACC parallel construct and on its gang loop;
! + with copy instead of the construct's reduction, and on CCE 21, the sum is right.
! control: fuzz/controls/cce-acc-parallel-and-gang-loop-reduction-lost-copy-not-reduction-control.f90 one change from the
! + finding; correct on cce19, cce20
! end site
