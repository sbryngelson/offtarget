! # Finding: NVHPC OpenACC does not copy back a derived-type variable
! # written through a component in a serial construct
!
! - compilers: NVHPC nvfortran 25.11 and 26.9, A100 (sm_80), -acc=gpu -gpu=cc80, separate and
!   managed memory, -O2
! - expected: c1= 203. xc has an exposed access in the serial construct and no visible data clause;
!   in that case "An aggregate variable will be treated as if it appears either: ... In a copy
!   clause otherwise" (OpenACC 3.4 §2.6.2 p.41 l.1388-1391). The access to xc%c1 is an access to xc (§2.6.2 l.1374), and a
!   derived type is a composite type, hence an aggregate (glossary p.159 l.5792-5796, 5807-5811)
! - actual: c1= 101 on both releases and both memory modes
! - control (same compiler): serial copy(xc) (data/reports/fuzz-stress-audit/r5-acc-component-control.f90):
!   203 on both releases and modes
! - other families: CCE 19/20/21 (ftn -h acc) give 203 on this program (MI300A HSA_XNACK 1 and 0, MI250X)
! - legality: legal by reading: serial runs one gang, one worker, one vector lane; xc is a local
!   variable of the main program
! - evidence: results/stress/audit/runs-nvhpc.jsonl. The confirmer gave needs_human (R22, no
!   cross-machine witness); the audit counts the MI300A results
program acc_component
  implicit none
  type :: t
    integer(8) :: c1
  end type t
  type(t) :: xc
  xc%c1 = 101
  !$acc serial
    xc%c1 = 2 * xc%c1 + 1
  !$acc end serial
  print '(a,i0)', 'c1= ', xc%c1
end program acc_component
! site:
! title: nvfortran -acc: derived-type variable without a data clause is not copied back from a serial region
! control: ../vendor/checks/src/nvhpc/control/nvhpc-acc-derived-type-component-not-copied-control.f90 serial copy(xc)
! end site
