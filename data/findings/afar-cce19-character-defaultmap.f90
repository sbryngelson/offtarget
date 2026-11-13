program p
  implicit none
  character :: ch
  character(len=4) :: s
  integer :: k
  ch = 'a'; s = 'abcd'; k = 1
  !$omp target
  ch = 'b'; s = 'wxyz'; k = 2
  !$omp end target
  print '(a,a,a,a,a,i0)', 'ch=', ch, ' s=', s, ' k=', k
end program
! site:
! title: amdflang: a Fortran character scalar referenced in a target region is treated as a firstprivate scalar (writes lost)
! control: ../vendor/checks/src/afar/control/afar-cce19-character-defaultmap-control.f90 ch and s mapped explicitly: map(tofrom:
! + ch, s)
! end site
! spec (requirement): In Fortran a character variable is not a scalar variable for OpenMP: the scalar variable
!   definition excludes the character type.
! "For Fortran, a scalar variable with intrinsic type, as defined by the base language, excluding character type."
!   (5.2 §1.2.6 p.14 l.7-8)
! spec (requirement): A variable referenced in a target construct that is not a scalar is implicitly mapped with
!   map-type tofrom, so a character variable is mapped and its modification is visible after the region.
! "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom."
!   (5.2 §5.8.1 p.149 l.4-5)
! spec (this program): ch and s are character variables referenced in the target region with no map or defaultmap
!   clause, so both are implicitly mapped tofrom and come back as b and wxyz; amdflang treats them as firstprivate
!   scalars and the writes are lost (k, an integer scalar, is firstprivate and keeps its value).
