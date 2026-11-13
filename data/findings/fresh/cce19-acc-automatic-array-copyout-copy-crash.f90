! # Finding (from the data/bench/fresh draft fresh-084): CCE 19 crashes on a two-dimensional
!   automatic array in copyout in copy mode (OpenACC)
!
! - source: data/bench/fresh/fresh-084.f90 (reconstructed from the ICON workaround at
!   src/atm_dyn_iconam/mo_nh_supervise.f90, icon-model 8597da45, line 765: an automatic array in
!   copyout, zeroed in kernels and filled in a parallel loop). Neither the kernels region nor the
!   copyin array matters; the automatic array's rank does (the one-dimensional form,
!   data/reports/fresh-drafts/d084-min.f90, is correct)
! - compilers: CCE 19.0.0 ftn -h acc -O2; MI300A HSA_XNACK=0, MI250X (Tioga) HSA_XNACK=0
! - expected: s 3150.0. copyout(w) on the data construct allocates w on the device at entry and
!   transfers it out at exit when the reference counters reach zero (OpenACC 3.4 §2.7.9 p.56
!   l.1932-1953); the parallel loop writes every element, so w(i, k) = i*k on the host after the
!   region and the sum over i = 1..20, k = 1..5 is 210 * 15 = 3150
! - actual: SIGSEGV (exit -11), nothing printed, three runs of three; at HSA_XNACK=1 correct
! - control (same compiler): w a fixed-size local w(20, 5) instead of the automatic w(nb, nl)
!   prints s 3150.0 at XNACK 0 and 1 (data/reports/fresh-drafts/d084-min2d-fixed.f90); so do an
!   allocatable vn_aux in the draft (d084-allocatable.f90) and the one-dimensional automatic array
!   (d084-min.f90)
! - other families: CCE 20.0.2 and 21.0.3 print s 3150.0 (both modes); NVHPC 25.11 and 26.9 print
!   s 3150.0 on this program and run the draft correctly (A100, separate and managed
!   memory); AFAR has no Fortran OpenACC
! - legality: legal by reading
! - evidence: results/fresh-drafts/tuo-p2.jsonl, tuo2-q2.jsonl, tuo3-r*-b.jsonl, tioga/tioga-b.jsonl,
!   wingtip/nv.jsonl, wingtip/nv4.jsonl (review)
module m
  implicit none
contains
  subroutine fill(nb, nl, s)
    integer, intent(in) :: nb, nl
    real(8), intent(out) :: s
    real(8) :: w(nb, nl)
    integer :: i, k
    !$acc data copyout(w)
    !$acc parallel loop collapse(2)
    do k = 1, nl
      do i = 1, nb
        w(i, k) = i * k
      end do
    end do
    !$acc end data
    s = sum(w)
  end subroutine fill
end module m

program main
  use m
  implicit none
  real(8) :: s
  call fill(20, 5, s)
  print *, 's', s
end program main
! site:
! title: ftn 19 (OpenACC): a two-dimensional automatic array in copyout crashes the run in copy mode
! control: ../vendor/checks/src/cce/control/cce19-acc-automatic-array-copyout-copy-crash-control.f90 w a fixed-size local array
! + w(20, 5) instead of the automatic w(nb, nl)
! end site
