! # Finding: CCE OpenACC treats a "declare create" module scalar as
! # firstprivate in a serial construct
!
! - compilers: CCE ftn 19.0.0, 20.0.2, 21.0.3 (-h acc), MI300A (gfx942) HSA_XNACK 1 and 0, and
!   MI250X (gfx90a, Tioga, HSA_XNACK 0); -O2
! - expected: g= 203. g is in a data clause on a declare directive, so its data attributes are
!   explicitly determined (OpenACC 3.4 §2.6 p.40 l.1331-1334); a variable in a data clause on a
!   visible declare directive gets no implicit data attribute (§2.6.2 p.41 l.1372-1373, 1387); the
!   data lifetime of a declare in a module's declaration section is the whole program (§2.13 p.81
!   l.2983-2986), and the global variable is statically allocated in device memory with structured
!   reference count one (§2.13.2 p.83 l.3051-3052). So the serial region writes the device copy
!   (set to 101 by "update device"), and "update self" returns 203
! - caveat: 3.4 does not define "visible" for a declare directive reached by USE association. Read
!   together, the sections above leave no textual support for a firstprivate reading, but the
!   finding rests on that reading of "visible"
! - actual: g= 101 (CCE 19/20/21, MI300A both XNACK settings; MI250X)
! - control (same compiler): serial present(g)
!   (data/reports/fuzz-stress-audit/r3-acc-declare-create-scalar-control.f90): 203 on CCE 19/20/21;
!   the earlier review's kernels form is 203 too
! - other families: NVHPC 25.11 and 26.9 (nvfortran -acc=gpu, A100, separate and managed) give 203
! - legality: legal by reading: serial, a module scalar, update device/self of a declared variable
! - evidence: results/stress/audit/runs.jsonl, runs-tioga.jsonl, runs-nvhpc.jsonl. The confirmer
!   gave needs_human (R22); the audit counts the A100 results as the other-family witness
module acc_scalar_m
  implicit none
  integer(8) :: g
  !$acc declare create(g)
end module acc_scalar_m
program acc_declare_scalar
  use acc_scalar_m
  implicit none
  g = 101
  !$acc update device(g)
  !$acc serial
    g = 2 * g + 1
  !$acc end serial
  !$acc update self(g)
  print '(a,i0)', 'g= ', g
end program acc_declare_scalar
! site:
! title: ftn -h acc: a module scalar in declare create is treated as firstprivate in a serial region (write lost)
! control: ../vendor/checks/src/cce/control/cce-acc-declare-create-scalar-serial-firstprivate-control.f90 serial present(g)
! end site
