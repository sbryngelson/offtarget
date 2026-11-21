! # Finding (GCC 16.2): gfortran -fopenacc for amdgcn: the result of a loop reduction in an async kernels construct is lost when the
!   reduction variable's address is never taken
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: wrong_answer (check=fail)
! - observed: `ok= 0` with `check=fail`; identical signature on 1 of 1 failing cells
! - expected: compiles and prints `ok= 1` with `check=pass`
! - rule: r has no data clause in the kernels construct, so it "will be treated as if it appears ... In a copy clause" (OpenACC 3.4
!   §2.6.2 p.41 l.1392-1393); the loop's reduction result is "combined with the value of the original var and stored in the original
!   var" by the end of the compute region (OpenACC 3.4 §2.9.11 p.71 l.2551-2555); and "The wait directive causes the local thread
!   ... to wait for completion of asynchronous operations" (OpenACC 3.4 §2.16.3 p.100 l.3721-3722), so after wait(1) r holds the
!   reduction
! - same-compiler control: controls/gcc-acc-async-kernels-reduction-lost-no-async-control.f90 (one change from this file: no async
!   clause; correct on gcc (GCC 16.2.0); site rows, check case site-fuzz--gcc-acc-async-kernels-reduction-lost)
! - other families: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the file correctly (site
!   rows, check case site-fuzz--gcc-acc-async-kernels-reduction-lost)
! - legality: legal by reading: r is reduced by the loop and read by the host only after wait(1), which completes the region and its
!   copy back; hf is written in one iteration and mapped by copy(hf); there is no data race. The rules witness and AMD flang's front
!   end accept the file and its control (offload.engine.prerun.check on Tuolumne, 2026-11-21). Reduced from the OpenACC fuzz sample
!   acc1 (seeds 1762, 63, 1336, generator fuzz-acc1, whose sequential runs printed the model's checksum); the result comes back when
!   the program prints r itself (taking its address), so the reproducer prints a value computed from r
program kasync
  use openacc, only: acc_on_device, acc_device_host
  implicit none
  integer, parameter :: n = 64
  integer :: i, r, hf
  r = 65535
  hf = 1
  !$acc kernels copy(hf) async(1)
    !$acc loop gang reduction(iand: r)
    do i = 1, n
      if (i == 1) hf = merge(1, 0, acc_on_device(acc_device_host))
      r = iand(r, i + 256)
    end do
  !$acc end kernels
  !$acc wait(1)

  print '(a,i0)', 'ok= ', merge(1, 0, r == 256)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', r == 256)
end program kasync

! site:
! title: gfortran OpenACC: async kernels loop reduction result lost
! summary: GCC 16.2's OpenACC on the MI300A loses the result of a loop reduction in a kernels construct with async when the program
! + never takes the variable's address; without async the result is right.
! control: fuzz/controls/gcc-acc-async-kernels-reduction-lost-no-async-control.f90 one change from the finding; correct on
! + gcc
! end site
