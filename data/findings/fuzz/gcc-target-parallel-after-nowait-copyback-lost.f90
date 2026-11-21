! # Finding (GCC 16.2): libgomp: a target parallel nowait that depends on a target nowait loses the first region's copy-back
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: wrong_answer (check=fail)
! - observed: `bad= 64` with `check=fail`; identical signature on 1 of 1 failing cells
! - expected: `bad= 0`, then `RESULT ran_on_host=0 check=pass`: the first target region sets every a(i) to 30011, its implicit
!   tofrom map copies a back, and the second region only reads a
! - rule: the second construct's task depends on the first: "For the in task-dependence-type, if the storage location of at least
!   one of the list items matches the storage location of a list item appearing in a depend clause with an out, inout,
!   mutexinoutset, or inoutset task-dependence-type on a construct from which a sibling task was previously generated, then the
!   generated task will be a dependent task of that sibling task." (OpenMP 5.2 §15.9.5 p.323 l.21-24), so the first target task,
!   with the copy-back of a at its end ("the original list item is updated as if the list item appeared in a from clause on a target
!   update directive", 5.2 §5.8.3 p.154 l.3-5), completes before the second starts; taskwait waits for both
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-target-parallel-after-nowait-copyback-lost)
! - same-compiler control: controls/gcc-target-parallel-after-nowait-copyback-lost-plain-target-control.f90 (one change from this
!   file; correct on gcc (GCC 16.2.0); site rows, check case site-fuzz--gcc-target-parallel-after-nowait-copyback-lost)
! - legality: legal by reading: two sibling target tasks ordered by depend(out: a) and depend(in: a), a taskwait before the host
!   reads a, a mapped by the first region implicitly (an array referenced in the region) and with map(to: a(1:n)) by the second,
!   which writes nothing; hf is mapped tofrom by the first region only. The rules witness (offload.engine.prerun) accepts it, and
!   other families' front ends compile and run it correctly (the rows)
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n)
  integer :: i, hf, bad
  a = 0
  hf = 1
  !$omp target nowait depend(out: a) map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      a(i) = 30011
    end do
  !$omp end target
  !$omp target parallel map(to: a(1:n)) nowait depend(in: a)
  !$omp end target parallel
  !$omp taskwait
  bad = count(a /= 30011)
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', bad == 0)
end program p

! site:
! title: libgomp: target nowait copy-back lost before a dependent target parallel
! summary: GCC 16.2: a target parallel nowait with depend(in: a), after a target nowait with depend(out: a) that writes a, leaves
! + the host's a unchanged (64 of 64 values) after taskwait; a plain target as the second construct gives the right values.
! control: fuzz/controls/gcc-target-parallel-after-nowait-copyback-lost-plain-target-control.f90 one change from the finding;
! + correct on gcc
! end site
