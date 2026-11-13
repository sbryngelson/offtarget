! scope: out of scope (host only: a Fortran output statement, no OpenMP; kept as a record)
! # Record (lead 3): CCE ftn prints one character of trim(merge('pass', 'fail', ok))
!
! - compiler: CCE ftn 19.0.0, 20.0.2, 21.0.3 and 21.0.4, with and without -fopenmp (-h noomp), -O0
!   and -O2 (Tuolumne)
! - expected: every line ends in pass (A check=pass, B check=pass, C len= 4, D check=pass, E
!   check=pass, F check=pass, G check=xpassy). merge('pass', 'fail', ok) is 'pass' when ok is
!   true (both sources have length 4, as MERGE requires), and TRIM of it is 'pass' (the Fortran 2008
!   standard's MERGE and TRIM).
! - actual: A check=p and B check=p (the trimmed merge as an output item, list-directed or with a
!   format, prints its first character); C, D, E, F, G are right: LEN of the same expression is 4,
!   TRIM of a variable holding it, the untrimmed merge, a constant mask and the expression inside
!   a concatenation all print pass.
! - other family: AFAR amdflang prints pass on every line.
! - found by: the data-environment pilot, whose first RESULT lines used
!   trim(merge('pass', 'fail', ok)) ("A false start is not counted").
! - legality: plain Fortran 2008 (no OpenMP); offload.engine.prerun.check's rules and AFAR flang front
!   end accept it (data/evidence/lead_probe/logs/legality_new.jsonl); no compiler under test, gfortran or gcc
!   is a legality witness.
! - scope: a host base-language defect: outside the device-offload scope (see data/reports/rulings.md),
!   so it is recorded here, not counted as an offload finding.
! - evidence: data/evidence/lead_probe/leads/tm_host.f90, tm_target.f90 (the same in a program with a target
!   region), data/evidence/lead_probe/logs/leads_tuolumne.jsonl and leads_tuolumne_noomp.txt
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
! site:
! disposition: out-of-scope host only: a Fortran output statement with no offload construct
! end site
