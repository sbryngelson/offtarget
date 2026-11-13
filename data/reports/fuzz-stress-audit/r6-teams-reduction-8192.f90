! Audit, candidate 6: a teams reduction over 2**24 iterations with
! num_teams(8192). All variables are integer(8); the sum is 8455717314 (more
! than 2**32). Expected: s= 8455717314
program teams_reduction
  implicit none
  integer(8) :: i, s, nn
  nn = 16777216_8
  s = 0
  !$omp target teams distribute parallel do num_teams(8192) thread_limit(256) reduction(+: s)
  do i = 1, nn
    s = s + mod(i * 715_8, 1009_8)
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 's= ', s
end program teams_reduction
