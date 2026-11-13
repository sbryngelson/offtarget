program p
  implicit none
  integer, parameter :: n = 16, m = 4
  integer :: o1(n, m), i, j
  integer(8) :: cs
  o1 = 0
  call kp(o1)
  cs = sum(int(o1, 8))
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
contains
  subroutine kp(o1)
    integer, intent(inout) :: o1(:, :)
    integer :: i, j
    !$omp target teams distribute parallel do map(tofrom: o1)
    do i = 1, n
      !$omp simd nontemporal(o1)
      do j = 1, m
        o1(i, j) = i + j
      end do
    end do
  end subroutine kp
end program p
! site:
! title: amdflang: "verification of lowering to FIR failed" for nontemporal on an assumed-shape dummy
! control: ../vendor/checks/src/afar/control/afar-nontemporal-assumed-shape-ice-control.f90 nontemporal(o1) removed from the simd
! + directive
! end site
! spec (requirement): The nontemporal clause on a simd construct takes a list of variables, and its text states no
!   restriction on their form, so an assumed-shape dummy array is a valid list item.
! "The nontemporal clause specifies that accesses to the storage locations to which the list items refer have low
!   temporal locality across the iterations in which those storage locations are accessed." (5.2 §10.4.1 p.236
!   l.21-22)
! spec (requirement): The list items of nontemporal may also appear in data-environment attribute clauses.
! "The list items of the nontemporal clause may also appear as list items of data-environment attribute clauses." (5.2
!   §10.4.1 p.236 l.23-24)
! spec (this program): nontemporal(o1) names an assumed-shape dummy that is also mapped by the enclosing target
!   construct; the spec text has no restriction against assumed-shape list items (it does not mention them), and
!   amdflang stops with a failed lowering to FIR.
