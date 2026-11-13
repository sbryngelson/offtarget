! CCE 21: a target teams distribute parallel do over 2**32 iterations does
! not run its last 256-iteration block (retitled; the file keeps
! its name). Found as a wrong sum when the loop fills an integer(8)
! allocatable of 2**32 elements on the device and a second loop reduces it
! (the reproduction gate's review queue, entries 86 and 75, the
! stress program runtime.alloc-omp at 2**32, which is already this one
! kernel). The reduction is right; the fill loop leaves the last 256
! elements unwritten.
! Spec: integer(8) indices and extents, so nothing overflows (the largest
! product is 642 * 2**32); every iteration of the loop runs once (5.2 §11.6 p.254
! distribute, §11.5 p.247 worksharing-loop); the array is mapped by target enter
! data map(alloc:) (§13.6 p.280) and the sum is a reduction on target teams
! distribute parallel do (§5.5.8 p.134), mapped tofrom (§17.2 p.341
! l.10-13). 2**32 * 8 bytes = 32 GiB on the host and 32 GiB on the device
! (MI300A: 128 GB).
! Expected: "s= 2164663527981" (642 is invertible mod 1009, so each run of
! 1009 consecutive i adds 0 + 1 + ... + 1008 = 508536).
! Observed (Tuolumne MI300A, -O2, OMP_TARGET_OFFLOAD=mandatory, one run at a
! time, 2026-10-26; data/evidence/gate_probe/logs/reduce.txt):
! - CCE 21.0.3, HSA_XNACK 0 and 1: s= 2164663393401 in 4 of 4 runs, 134580
!   short: exactly the sum of mod(i*642, 1009) over i = 2**32-255 .. 2**32.
! - Localization (after the later runs;
!   data/evidence/gate_probe/reduce/): the same device fill, then target update from
!   and a check on the host (fill_check_32.f90): "wrong= 256 big(nn)= 0
!   big(nn-256)= 814" at XNACK 0, and at XNACK 1 big(nn)= -1 (the host's
!   initial value, never overwritten): the last 256 iterations of the fill
!   loop did not run. The array filled on the host, mapped to, and reduced
!   by the same reduction loop (hostfill_reduce_32.f90): s= 2164663527981
!   (right), both modes.
! - Controls on CCE 21: the same program at 2**31 elements (alloc_31.f90):
!   s= 1082331768994 (right); the same 2**32 iterations as one reduction loop
!   without the array (iter_32.f90): right (8 runs).
! - CCE 19.0.0 (XNACK 0 and 1) and 20.0.2 (XNACK 0 and 1): a GPU memory
!   access fault (SIGABRT) at 2**32 in every run; CCE 20 faults in the fill
!   loop alone (fill_check_32.f90); at 2**31 neither finishes within 300 s.
!   data/reports/fuzz-stress.md records CCE 19/20's fill-and-reduce shape as
!   wrong from 2**22 elements under candidate 6; its cause is not shown here,
!   so this finding claims CCE 21 only.
! Another family: AFAR amdflang (XNACK 0 and 1) and nvfortran 25.11 and 26.9
! (A100 80 GB, separate memory): s= 2164663527981
! (data/evidence/gate_probe/logs/wingtip5.log).
! CCE: ftn -fopenmp -O2 (module load cce/21.0.3 craype-accel-amd-gfx942 rocm)
! Run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out (needs 64 GiB free)
program p
  implicit none
  integer(8) :: i, nn, s
  integer(8), allocatable :: big(:)
  nn = 2_8**32
  s = 0
  allocate(big(nn))
  !$omp target enter data map(alloc: big)
  !$omp target teams distribute parallel do
  do i = 1, nn
    big(i) = mod(i * 642, 1009_8)
  end do
  !$omp end target teams distribute parallel do
  !$omp target teams distribute parallel do reduction(+: s)
  do i = 1, nn
    s = s + big(i)
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(delete: big)
  deallocate(big)
  print '(a,i0)', 's= ', s
end program p
! site:
! title: ftn 21: target teams distribute parallel do over 2**32 iterations skips its last 256-iteration block
! end site
