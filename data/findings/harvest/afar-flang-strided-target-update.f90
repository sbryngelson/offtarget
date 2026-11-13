! # Finding: AFAR amdflang ignores the stride of a Fortran array
! # section in `target update`: from(a(1:7:2)) copies all of a
!
! - compilers: AFAR amdflang 24.0.0git (drop 24.3.0), -O2: MI300A gfx942
!   (HSA_XNACK=0; gate below) and MI250X gfx90a (HSA_XNACK=0; one probe of
!   three runs, not gated)
! - expected: a:  11.0   2.0  13.0   4.0  15.0   6.0  17.0   8.0
!   / strided bad= 0 contiguous bad= 0
! - actual: a:  11.0  12.0  13.0  14.0  15.0  16.0  17.0  18.0
!   / strided bad= 4 (every element of a, a(8) too, comes back)
!   (results/harvest/probe/gate/afar-flang-strided.r*.jsonl; gfx90a:
!   results/harvest/probe/f1f2.jsonl, strided_f.f90)
! - gate (four environments on gfx942 X0, tools/campaigns/harvest_probe.py
!   --gate-envs, offload.engine.gate.judge): the stored run (three repeats) and
!   (a), (b), (d) on tuolumne1020, (c) on tuolumne1021: the same wrong
!   answer in every run; confirmed.
! - rule: "The list items may include array sections with stride
!   expressions ... If a list item is an array or array section then it is
!   treated as if it is replaced by each of its array elements in the
!   clause" (OpenMP 5.2 §5.9 p.165 l.13-17); a(1:7:2) is a(1), a(3), a(5),
!   a(7) (a subscript triplet, Fortran 2008 6.5.3.3.2).
! - copy mode only: with storage shared between host and device
!   (HSA_XNACK=1) every device write is visible, so elements outside the
!   section may differ legitimately.
! - same-compiler controls (correct): update from(b(1:4)) (contiguous);
!   AFAR amdclang's C form from(a[0:4:2]) (harvest/cce-c-strided-target-update.c).
! - other families: none runs it: CCE ftn 19.0.0, 20.0.2, 21.0.3 reject it
!   ("ftn-1747: The stride specified for array "A" in the MAP clause must
!   not be greater than 1", although its man page says "Non-contiguous
!   updates are supported for normal array slice expressions that specify a
!   lower bound, upper bound, and optional stride"); NVHPC nvfortran 25.11
!   and 26.9 reject it (NVFORTRAN-S-0034 syntax error at the stride).
! - legality: legal by the quoted spec text only (no independent compiler
!   witness: AFAR is the compiler under test, and CCE and NVHPC reject the
!   stride). offload.engine.rules with the race rule accepts it. 5.2 §5.9 allows
!   strided array sections in motion clauses; the map clause's contiguity
!   restriction (CCE's ftn-1747 speaks of "the MAP clause") does not apply
!   to `target update`. CCE's rejection is the finding
!   fuzz/s1-6888-cce21.f90 (ftn-1747); NVHPC's is a candidate defect. That
!   finding calls AFAR correct on its strided `to`: its program checks the
!   updated elements only, where an ignored stride would not show.
! - found by: while reducing the CCE C strided-update failures of
!   llvm-project offload/test/offloading/strided_update/ (no Fortran test
!   there).
! AFAR: amdflang -fopenmp --offload-arch=gfx942 -O2
! Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
program strided_f
  use omp_lib
  implicit none
  real(8) :: a(8), b(8)
  integer :: i, bad_a, bad_b, on_host
  do i = 1, 8
    a(i) = i
    b(i) = i
  end do
  on_host = 1
  !$omp target data map(to: a, b)
  !$omp target map(from: on_host)
  if (omp_is_initial_device()) then
    on_host = 1
  else
    on_host = 0
  end if
  do i = 1, 8
    a(i) = a(i) + 10
    b(i) = b(i) + 10
  end do
  !$omp end target
  !$omp target update from(a(1:7:2))
  !$omp target update from(b(1:4))
  !$omp end target data
  bad_a = 0
  bad_b = 0
  do i = 1, 8
    if (mod(i, 2) == 1) then
      if (a(i) /= i + 10) bad_a = bad_a + 1
    else
      if (a(i) /= i) bad_a = bad_a + 1
    end if
    if (i <= 4) then
      if (b(i) /= i + 10) bad_b = bad_b + 1
    else
      if (b(i) /= i) bad_b = bad_b + 1
    end if
  end do
  print '(a,8f6.1)', 'a:', a
  print '(a,i0,a,i0)', 'strided bad= ', bad_a, ' contiguous bad= ', bad_b
  if (bad_a == 0) then
    print '(a,i0,a)', 'RESULT ran_on_host=', on_host, ' check=pass'
  else
    print '(a,i0,a)', 'RESULT ran_on_host=', on_host, ' check=fail'
  end if
end program strided_f
! site:
! title: amdflang: target update from a strided array section copies the whole array
! end site
