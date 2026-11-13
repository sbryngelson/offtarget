! NVHPC 25.11 and 26.9 (nvfortran), NVIDIA A100 80GB PCIe
! (wingtip, sm_80): the Fortran form of nvhpc-c-acc-atomic-update-sum-ice.c.
! nvfortran rejects the OpenACC atomic update b(i) = b(i) + 2*a(i) + 1
! ("NVFORTRAN-S-0155-Invalid atomic update expression"), and in a gang loop
! its front end then crashes ("nvfortran-Fatal-.../maintainers/fort2 TERMINATED by
! signal 11"), at -O0 and -O2, for -acc=gpu and -acc=multicore. In a plain
! parallel loop on a scalar (x = x + v + 1) it only rejects ("Invalid atomic
! update expression", "Invalid atomic region"), without the crash.
! Spec: one Fortran form of an atomic update is "x = x operator expr", and
! "The expression x operator expr must be mathematically equivalent to x
! operator (expr). This requirement is satisfied if the operators in expr
! have precedence greater than operator, or by using parentheses around expr
! or subexpressions of expr" (OpenACC 3.4 §2.12, p.79-80).
! b(i) + 2*a(i) + 1 is (b(i) + 2*a(i)) + 1, which is b(i) + (2*a(i) + 1) for
! integers: the precedence and parentheses forms are sufficient, not
! necessary, so the statement is a legal update. Written
! b(i) = b(i) + (2*a(i) + 1) it compiles and gives sum=4224.
! Expected: "sum=4224" (a diagnostic would at least not be a crash).
! Observed (2026-10-25, nvfortran 25.11-0 and 26.9-0, the flags below and
! -O0, -acc=multicore): compile exit status 2 with the two messages above,
! on both releases (log: data/evidence/acc_c_probe/atomic/run.log, gang.f90).
! Found by the catalog: acc34-clause-gang, acc34-clause-gang-dim and
! acc34-directive-loop, all gang loops: the front end crashes in 11 of their
! 12 NVHPC cells (gang-dim on 25.11 in separate memory rejects without the
! crash; results/acc_matrix.jsonl); reduced by hand. That rejection without the crash was 1 compile in 157;
! the other 156 (the gate's reruns and the later repeats) crashed
! (data/evidence/gate_probe/logs/wingtip1-4.log): the 12th cell crashes too, not
! every time.
! NVHPC: nvfortran -acc=gpu -gpu=cc80 -gpu=mem:separate -O2
program p
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  !$acc parallel num_gangs(4) copyin(a) copy(b)
  !$acc loop gang
  do i = 1, n
    !$acc atomic update
    b(i) = b(i) + 2*a(i) + 1
  end do
  !$acc end parallel
  print '(a,i0)', 'sum=', sum(b)
end program p
! site:
! title: nvc/nvfortran -acc: atomic update x = x + v + 1 rejected, then internal compiler error (nvc) or fort2 crash (nvfortran)
! control: ../vendor/checks/src/nvhpc/control/nvhpc-acc-atomic-update-sum-fort2-crash-control.f90 b(i) = b(i) + (2*a(i) + 1), the
! + right-hand side
! + in parentheses
! same_as: nvhpc-c-acc-atomic-update-sum-ice
! end site
