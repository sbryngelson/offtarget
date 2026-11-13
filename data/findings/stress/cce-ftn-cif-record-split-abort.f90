! # Finding: CCE ftn aborts when an optimizer message record has "-1" at its 1024th character
!
! - compilers: CCE ftn 17.0.1, 18.0.1, 19.0.0, 20.0.0, 20.0.2, 21.0.0, 21.0.3, 21.0.4, the same on
!   Tuolumne (craype-accel-amd-gfx942) and Tioga (gfx90a), 2026-10-25; the defect is on the host side
! - build: save this file as stress.f90 in the directory
!     A = /tmp/cce-cif/ + 202 letters a + -1aa        (219 characters; one directory below /tmp/cce-cif)
!   and run `ftn -fopenmp -O2 -c stress.f90` there (the pinned prelude: module load cce/<v>
!   craype-accel-amd-gfx942 rocm/<r>; module unload cray-mpich). tools/jobs/run_ftn_cif_split.sh repro does it.
! - expected: the compile succeeds (exit 0) and prints the program's 3 messages (ftn-878 warnings: glob is
!   use associated twice in c2, c1 and the main program). Legal Fortran 2008 with OpenMP 5.0 directives,
!   by reading: `!$omp declare target (extended-list)` (5.0 §2.12.7 p.181 l.15) gives gv a device copy
!   ("initialized once ... never removed", p.182 l.19-22); `!$omp declare target` without clauses in a
!   function makes that function a device procedure ("an implicit extended-list ... of one item is formed
!   from the name of the enclosing ... function subprogram", p.183 l.21-23); `target update to(gv)`
!   (§2.12.6); each iteration writes its own out(i). "An implementation of the OpenMP API is compliant if
!   and only if it compiles and executes all other conforming programs" (5.0 §1.6 p.31 l.11-12). A run
!   (not part of this finding) prints sum=145702.
! - actual: every release above: SIGABRT (exit 6) with "free(): invalid pointer" (17.0.1: "double free or
!   corruption (out)"), no messages, no object. Also at -O3 and when linking; not at -O0 (no optimizer
!   messages). AFAR amdflang compiles the file in A (-fopenmp --offload-arch=gfx942 -O2 -c).
! - control: the same file in the directory of the same length with -2aa in place of -1aa compiles on every
!   release with its 3 messages (the check case's control,
! + ../vendor/checks/src/cce/control/cce-ftn-cif-record-split-abort-control.f90).
!   What matters is the absolute path of the source file: compiled from another working directory with the
!   source named by its path in A it aborts; compiled in A with the source taken from another directory it
!   does not; -o, -J, PWD and TMPDIR do not matter.
! - mechanism (CCE 19.0.0 binaries, gdb, valgrind, strace): optcg's m_cif_merge_messages (and ftnfe's
!   finish_msgs_and_cif) copy the compiler-information records into the CIF the driver prints messages
!   from with `fgets(buf, 1024)` per chunk, stopping at the first chunk whose strtol value is -1 (the end
!   record). IPA's message 'Tree "g2" was flattened.#"g2"(<path>/stress.f90:22)   "g3"(<path>/stress.f90:10)'
!   carries the absolute source path, twice per record, so in A the record is longer than 1023 characters
!   and its chunk at offset 1023 starts with "-1aa/stress.f90...": the copy stops there and the CIF is cut
!   mid-record. The driver (Cif_Cifconv, write_unit) then calls free() on a pointer 984 bytes into a
!   16 KiB block of its CIF arena (valgrind, the tu12 program: "Invalid free"), and glibc aborts.
!   A cut in another record can instead give exit 0 with every later message silently dropped.
! - the rule, verified on 1,749 compiles (CCE 19 for all; 20.0.2 and 21.0.3 for the tu12 set, identical):
!   in every compile where some record line, with the path substituted, has "-1" not followed by a digit at
!   offset 1023 (or 2046, ...), the compile aborted or printed fewer messages than the control; in every
!   other compile it printed all of them; no abort without such a split (tools/campaigns/ftn_cif_split.py,
!   data/reports/fuzz-stress-audit/ftnpath/). Whether a cut aborts depends on where the CIF is cut (here: in
!   g2's flattening record, 42 of 42 designed directories of 219-260 characters abort).
! - origin: the stress campaign's "path-dependent" ftn abort (data/reports/fuzz-stress.md F2): tu.plain-omp-12
!   in /tmp/<user>-stress/st-tu.plain-omp-12-1-abcd1234 has "12-1-abcd" in its directory name, and IPA's
!   message for k0001_g7 puts that "-1" at offset 1023 (data/reports/fuzz-stress-audit/ftn-path-abort-tu12.f90)
module glob
  implicit none
  integer(8) :: gv = 0
  !$omp declare target(gv)
end module glob
module c3
  use glob
  implicit none
contains
  function g3(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = x + gv
  end function g3
end module c3
module c2
  use glob
  use c3
  implicit none
contains
  function g2(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = g3(mod(x * 5, 1013_8) + 2) + 2
  end function g2
end module c2
module c1
  use glob
  use c2
  implicit none
contains
  function g1(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = g2(mod(x * 5, 1013_8) + 1) + 1
  end function g1
end module c1
program chain
  use glob
  use c1
  implicit none
  integer(8) :: out(256), s
  integer :: i
  gv = 77
  !$omp target update to(gv)
  out = 0
  !$omp target teams distribute parallel do map(tofrom: out)
  do i = 1, 256
    out(i) = g1(int(i, 8))
  end do
  !$omp end target teams distribute parallel do
  s = sum(out)
  print '(a,i0)', 'sum=', s
end program chain
! site:
! title: ftn: compiler aborts (free(): invalid pointer) when an optimizer message record has "-1" at its 1024th character
! + (path-dependent)
! control: ../vendor/checks/src/cce/control/cce-ftn-cif-record-split-abort-control.f90 the same file in a directory of the same
! + length
! + with -2
! + in place of -1
! end site
