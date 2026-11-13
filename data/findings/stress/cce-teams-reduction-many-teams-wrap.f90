! # Draft finding: data/reports/fuzz-stress-audit/r6-teams-reduction-65536.f90 on cce19
!
! - compiler: cce19
! - toolchain: cce19; arch: gfx942; machine: tuolumne; memory mode: copy; opt: -O2
! - program: file data/reports/fuzz-stress-audit/r6-teams-reduction-65536.f90 (f90, version 52, sha256 3713620f5e7f1159)
! - expected: s= 8455717314 (trusted; elision + metamorphic + model)
! - actual: wrong_answer s= 626787243 (expected s= 8455717314)
! - verdict: compiler_bug by rule R20-runtime-bug: a legal program fails at run time, deterministically, against an expected value
!   from two or more independent sources with an executed witness, and another toolchain, mode, arch or the elision gives the
!   expected value
! - reason: expected trusted s= 8455717314 (elision + metamorphic + model): elision + metamorphic + model agree; witnesses:
!   afar/gfx942/copy, cce21/gfx942/copy, elision
! - citations: RUL-DERIVED-NEEDS-EXECUTION (rulings.md); RUL-WITNESS-PER-MODE (rulings.md);
!   RUL-SAME-COMPILER-RUNS (rulings.md); RUL-PRESENCE-WITNESS (rulings.md); RUL-METAMORPHIC-OTHER-FAMILY
!   (rulings.md)
! - legality: legal: read against the spec (audit and re-review); checked by scope, offload.engine.rules, flang (no checker of
!   the family under test)
! - witnesses: afar/gfx942/copy, cce21/gfx942/copy, elision
! - withdrawn: none
!
! Audit, candidate 6: a teams reduction over 2**24 iterations with
! num_teams(65536). All variables are integer(8); the sum is 8455717314 (more
! than 2**32). Expected: s= 8455717314
program teams_reduction
  implicit none
  integer(8) :: i, s, nn
  nn = 16777216_8
  s = 0
  !$omp target teams distribute parallel do num_teams(65536) thread_limit(256) reduction(+: s)
  do i = 1, nn
    s = s + mod(i * 715_8, 1009_8)
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 's= ', s
end program teams_reduction
! spec (requirement): a reduction clause on a teams construct gives the initial task of every team a private copy of the list
!   item, and at the end of the region the original list item is combined with the final value of every private copy, whatever
!   number of teams (within the num_teams bounds) was created, so the sum does not depend on num_teams.
! "For the teams construct, one or more private copies of each list item are created for the initial task of each team in the
!   league, as if the private clause had been used. For the loop construct, private copies are created and used in the construct
!   according to the description and restrictions in Section 5.3. At the end of a region that corresponds to a construct for which
!   the reduction clause was specified, the original list item is updated by combining its original value with the final value of
!   each of the private copies, using the combiner of the specified reduction-identifier." (5.2 §5.5.8 p.135 l.4-10)
! "The num_teams clause specifies the bounds on the number of teams created by the construct on which it appears. lower-bound
!   specifies the lower bound and upper-bound specifies the upper bound on the number of teams requested. If lower-bound is not
!   specified, the effect is as if lower-bound is specified as equal to upper-bound. The number of teams created is implementation
!   defined, but it will be greater than or equal to the lower bound and less than or equal to the upper bound." (5.2 §10.2.1
!   p.233 l.10-15)
! spec (this program): the target teams distribute parallel do reduction(+: s) with num_teams(65536) must give the same sum as
!   any other legal team count (8455717314); CCE 19 returns a different value, while num_teams(8192) is correct.
! site:
! title: A reduction on target teams distribute parallel do with num_teams(65536) gives a wrong sum (8192 teams is correct)
! control: ../vendor/checks/src/cce/control/cce-teams-reduction-many-teams-wrap-control.f90 num_teams(8192) instead of
! + num_teams(65536)
! end site
