! lead 3: host only, no OpenMP: trim(merge('pass', 'fail', ok))
program tm
  implicit none
  logical :: ok
  character(len=4) :: c
  ok = .true.
  print *, 'A check=', trim(merge('pass', 'fail', ok))
  print '(a,a)', 'B check=', trim(merge('pass', 'fail', ok))
  print *, 'C len=', len(trim(merge('pass', 'fail', ok)))
  c = merge('pass', 'fail', ok)
  print *, 'D check=', trim(c)
  print *, 'E check=', merge('pass', 'fail', ok)
  print *, 'F check=', trim(merge('pass', 'fail', .true.))
  print *, 'G check=', 'x'//trim(merge('pass', 'fail', ok))//'y'
end program tm
