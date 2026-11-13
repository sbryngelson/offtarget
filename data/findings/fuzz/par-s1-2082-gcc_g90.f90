! Minimized by compliance.fuzz_min from fuzz seed 2082 (fuzz-3), then reduced by hand (coverage parity review, 2026-10-29).
! toolchain: gcc_g90 (-O2, HSA_XNACK=0, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (ice: internal compiler error: in simplify_subreg, at simplify-rtx.cc:8291)
! expected: compiles; prints `bad= 0` and `RESULT ran_on_host=0 check=pass`
! observed: `internal compiler error: in simplify_subreg, at simplify-rtx.cc:8291` from the amdgcn offload compiler
!   (accel/amdgcn-amdhsa/lto1, -march=gfx90a; in the RTL combine pass), located at the target directive (`!$omp target map(tofrom:
!   host_flag)`, column 37); mkoffload and the link fail. Site matrix: the same on tioga39 in environments (a), (b), (d), and in (c)
!   on another node. The nvptx build (gcc_sm80) compiles and runs this file correctly (mandatory pass 5 of 5; unset pass 5 of 5), as
!   do AFAR, CCE 19/20/21/21.0.4 and NVHPC 25.11/26.9 in every site-matrix environment. Evidence:
!   results/parity/tioga/gcc_g90/probes.jsonl, results/parity/wingtip/gcc_sm80/probes.jsonl, the site's finding matrix
!   (data/vendor/checks/results-site), and the one-change probes under results/parity/probes-r2 (cptr_r4.f90: this program with one
!   more, unused, integer variable).
! control (compiles; correct on gcc_g90, mandatory pass 5 of 5, unset pass 5 of 5): the same program with `o1` a complex array
!   instead of a pointer to one (controls/gcc-complex-pointer-store-control.f90). Other one-change probes on gcc_g90: a real
!   pointer array compiles and runs correctly; so does storing the loop index `i` instead of `ic(i, 2)`; storing
!   `mod(mod(ic(i, 2), 13), 1009)` (the fuzz program's expression), `cmplx(...)` or `real(ic(i, 2))`, with the loop ascending or
!   descending, fails to compile too.
! Legal OpenMP 5.2: the two witnesses that are neither GCC nor a compiler of this finding, offload.engine.rules and AFAR
! flang's front
!   end, accept this program and the control (offload.engine.prerun.check on results/parity/probes-r2/cptr_r4.f90 and
!   cptr_ctl_array.f90, the same code with one more unused variable and no comments;
!   results/parity/tioga/results/parity/legality.jsonl), and the minimized fuzz program before them; the fuzz program passed the
!   campaign's legality gate (the same two witnesses). GCC is a compiler under test only and never a legality witness.
program cptr_store
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 24
  integer :: ic(n, 2), i, host_flag, bad
  complex, pointer :: o1(:)
  complex, target :: o1t(n)
  o1 => o1t
  do i = 1, n
    ic(i, 1) = 0
    ic(i, 2) = mod((i + 14) * 24 + 22, 101) - 1
  end do
  o1t = 0
  host_flag = 1
  !$omp target map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = n, 1, -1
      ! an integer array element stored into a complex pointer array
      o1(i) = ic(i, 2)
    end do
  !$omp end target
  bad = 0
  do i = 1, n
    if (o1t(i) /= cmplx(ic(i, 2), 0.0)) bad = bad + 1
  end do
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program cptr_store
! site:
! title: A complex pointer array written in a target region: internal compiler error in the amdgcn offload compiler
! summary: GCC 16.2's amdgcn offload compiler (gfx90a) stops with an internal compiler error in its RTL combine pass on a
! + target region that stores an integer array element into a complex pointer array. The same program with a complex array
! + instead of the pointer compiles and runs correctly, and the A100 build of GCC compiles and runs this file. Reduced from a
! + fuzz program.
! control: fuzz/controls/gcc-complex-pointer-store-control.f90 o1 a complex array instead of a pointer
! end site
! spec (requirement): a pointer array that a target region references and no clause names is not a scalar, so it is mapped
!   tofrom, and an associated pointer in a map clause maps its pointer target too, so storing through the pointer in the region is
!   legal. The specification does not describe internal compiler errors, so no text covers the failure itself.
! "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom." (5.2
!   §5.8.1 p.149 l.4-5)
! "If a list item in a map clause is an associated pointer and the pointer is not the base pointer of another list item in a map
!   clause on the same construct, then it is treated as if its pointer target is implicitly mapped in the same clause. For the
!   purposes of the map clause, the mapped pointer target is treated as if its base pointer is the associated pointer." (5.2
!   §5.8.3 p.152 l.1-4)
! spec (this program): the target region stores the integer elements ic(i, 2) into the complex pointer array o1 (pointer to
!   o1t); GCC 16.2's amdgcn offload compiler (gfx90a) stops with an internal compiler error in the RTL combine pass instead of
!   compiling the store, while a complex array in place of the pointer compiles.
