"""A legal OpenMP 5.0 Fortran program: a chain of D declare-target functions, one per module,
each module using the global module and the next one; the target region calls the head."""
import sys
D = int(sys.argv[1])
o = ["module glob", "  implicit none", "  integer(8) :: gv = 0", "  !$omp declare target(gv)", "end module glob"]
for i in range(D, 0, -1):
    o += [f"module c{i}", "  use glob"] + ([f"  use c{i+1}"] if i < D else []) + ["  implicit none", "contains",
          f"  function g{i}(x) result(r)", "    !$omp declare target", "    integer(8), intent(in) :: x", "    integer(8) :: r",
          (f"    r = g{i+1}(mod(x * 5, 1013_8) + {i}) + {i}" if i < D else "    r = x + gv"),
          f"  end function g{i}", f"end module c{i}"]
o += ["program chain", "  use glob", "  use c1", "  implicit none", "  integer(8) :: out(256), s", "  integer :: i",
      "  gv = 77", "  !$omp target update to(gv)", "  out = 0",
      "  !$omp target teams distribute parallel do map(tofrom: out)", "  do i = 1, 256", "    out(i) = g1(int(i, 8))", "  end do",
      "  !$omp end target teams distribute parallel do", "  s = sum(out)", "  print '(a,i0)', 'sum=', s", "end program chain"]
print("\n".join(o))
