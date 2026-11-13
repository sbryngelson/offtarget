! # Finding (from the data/bench/fresh draft fresh-097): CCE rejects a common block name in a
!   map clause
!
! - source: data/bench/fresh/fresh-097.f90 (GCC Bugzilla 115577 with the reader of GCC PR 115559): a
!   common block in declare target link, mapped by name on target enter data. CCE rejects the map
!   clause with or without declare target, with or without a map type, on target enter data and on
!   target; this reproducer is the shortest form
! - compilers: CCE 19.0.0, 20.0.2 and 21.0.3 ftn, -fopenmp -O2
! - expected: compiles and prints wild-check: pass. A Fortran list item may be "a common block name
!   (enclosed in slashes)" (OpenMP 5.2 §3.2.1 p.61 l.6), and "When a named common block appears in
!   an OpenMP argument list, it has the same meaning and restrictions as if every explicit member of
!   the common block appeared in the list" (l.11-13); the map clause takes a locator list (§5.8.3
!   p.150), whose items are variable list items (§3.2.1 p.61 l.7-8). OpenMP 5.0, which HPE claims in
!   full ("CCE supports full OpenMP 5.0", intro_openmp(7)), already says it: "A list item is a
!   variable, array section or common block name (enclosed in slashes) ... a common block name
!   specified in a data-sharing attribute, a data copying or a data-mapping attribute clause must be
!   declared to be a common block in the same scoping unit" (5.0 §2.1 p.39 l.11-20)
! - actual: ftn-534: 'Common block "MYCOMMON" must not be specified on the MAP clause on directive
!   !$OMP TARGET.' (and "... TARGET ENTER DATA." for the draft), every release, both memory modes
! - control (same compiler): the members named instead, map(to: A, B, C), compile and print
!   wild-check: pass (data/reports/fresh-drafts/d097-target-members.f90, d097-members.f90)
! - other families: AFAR compiles and prints wild-check: pass (MI300A HSA_XNACK 1 and 0; MI250X).
!   NVHPC 25.11 rejects the draft's declare target link(/mycommon/) as a syntax error and 26.9 says
!   LINK is not implemented
! - legality: legal by reading (5.0 and 5.2 text above; the common block is declared in the scoping
!   unit of the clause)
! - evidence: results/fresh-drafts/tuo-p1.jsonl, tuo2-q4.jsonl, tuo3-r*-c.jsonl, tioga/tioga-d.jsonl (review)
program main
   integer :: A(2), C, r
   real :: B
   common /mycommon/ A, B, C
   A = [1, 2]; B = 2.0; C = 7
   r = 0
   !$omp target map(to: /mycommon/) map(from: r)
     if (A(1) == 1 .and. A(2) == 2 .and. B == 2.0 .and. C == 7) r = 1
   !$omp end target
   if (r == 1) then
     print *, 'wild-check: pass'
   else
     print *, 'wild-check: fail'
   end if
end program main
! site:
! title: ftn: a common block name in a map clause is rejected (ftn-534)
! control: ../vendor/checks/src/cce/control/cce-common-block-name-in-map-rejected-control.f90 the members named instead: map(to:
! + A, B, C)
! end site
