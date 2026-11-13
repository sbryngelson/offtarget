! NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), managed memory
! (-gpu=mem:managed): after the OpenACC shutdown directive a HOST access to
! an allocatable array ends the program with SIGSEGV; the same program is
! correct in separate memory (the compiler's default).
! Spec: "The shutdown directive shuts down the connection to the given
! device or devices of the given device type, and frees any associated
! runtime resources. This ends all data lifetimes in device memory"
! (OpenACC 3.4 §2.14.2 p.86). It ends device data lifetimes; the host array
! is host data of the program (no data clause names it here), so reading it
! on the host afterwards is defined. Managed memory is NVHPC's mode in which
! "Dynamically allocated host data are placed in CUDA Managed Memory" (HPC
! Compilers User's Guide 25.11 §5.4): the program's own host allocation
! becomes a runtime resource that shutdown frees.
! Expected: "after shutdown" and "sum 64", exit 0.
! Observed (2026-10-24, nvfortran 25.11-0, -O2, two runs, the same):
! - -gpu=mem:separate: "after shutdown", "sum 64", exit 0 (correct);
! - -gpu=mem:managed: no output, exit status 139 (SIGSEGV; the buffered
!   output is lost).
! Found by the catalog: acc34-directive-shutdown is correct in separate
! memory and crashes in managed memory (catalog/mode_differences.yaml
! nvhpc_entries, class managed_failure); reduced by hand to this program.
! NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
! the same flags): still present -- the same: managed memory SIGSEGV (exit 139), separate correct.
! Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
! each with its own runtime libraries (LD_LIBRARY_PATH = the release's
! compilers/lib; the first 26.9 runs had loaded 25.11's): still present
! on both releases, the same output.
! NVHPC: nvfortran -acc=gpu -gpu=cc80 -gpu=mem:managed -O2
! Run:   ./a.out
program p
  implicit none
  integer, allocatable :: a(:)
  allocate(a(64))
  a = 1
  !$acc shutdown
  print *, 'after shutdown'
  print *, 'sum', sum(a)
end program p
! site:
! title: nvfortran -acc -gpu=mem:managed: host access to an allocatable after !$acc shutdown ends in SIGSEGV
! control: ../vendor/checks/src/nvhpc/control/nvhpc-managed-acc-shutdown-host-access-control.f90 the shutdown directive removed
! end site
