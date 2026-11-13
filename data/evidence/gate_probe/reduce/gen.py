#!/usr/bin/env python3
"""Reproducers for the reductions asked
for (written to this directory):
* red_c_<N>.c: N int64 sum reductions on target teams distribute parallel
  for (the stress program scalars-c-64's kernel k0012, alone);
* red_acc_<N>.f90: N integer sum reductions on an OpenACC parallel loop
  (the stress program scalars.reduction-acc-200's kernel, alone);
* alloc_<e>.f90: fill and reduce an integer(8) allocatable of 2**e elements
  (stress runtime.alloc), and iter_32.f90: the same 2**32 iterations
  without the array (control).
Each prints the number of wrong values (bad= 0 expected) and the values.
    python3 -I data/evidence/gate_probe/reduce/gen.py"""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def red_c(n: int) -> str:
    v = ", ".join(f"s{k}" for k in range(1, n + 1))
    init = "\n".join(f"  s{k} = {100 + k};" for k in range(1, n + 1))
    body = "\n".join(f"    s{k} += {k};" for k in range(1, n + 1))
    chk = "\n".join(f"  if (s{k} != {100 + 5 * k}) {{ bad++; if (first < 0) {{ first = {k}; "
                    f"fv = (long) s{k}; }} }}" for k in range(1, n + 1))
    return f"""// {n} int64 sum reductions on one combined target
// construct (the kernel k0012 of the stress program scalars-c-64, alone).
// Each s_k starts at 100 + k and adds k in each of 4 iterations, so it ends
// at 100 + 5k (OpenMP 5.2 §5.5.8; §17.2 p.340: on a combined target
// construct a reduction list item is also map(tofrom)). Expected: bad= 0
#include <stdio.h>
#include <stdint.h>
int main(void) {{
  int64_t {v};
{init}
  #pragma omp target teams distribute parallel for reduction(+: {v})
  for (int ii = 0; ii < 4; ii++) {{
{body}
  }}
  int bad = 0, first = -1;
  long fv = 0;
{chk}
  printf("bad= %d first= %d (value %ld, expected %ld) s1= %ld s{n}= %ld\\n", bad, first, fv,
         first < 0 ? 0L : 100L + 5L * first, (long) s1, (long) s{n});
  return 0;
}}
"""


def red_acc(n: int) -> str:
    v = [f"s{k}" for k in range(1, n + 1)]
    lines = []
    for i in range(0, n, 10):
        lines.append(", ".join(v[i:i + 10]))
    decl = "\n".join(f"  integer :: {x}" for x in lines)
    red = ", &\n  !$acc& ".join(lines)
    init = "\n".join(f"  s{k} = {100 + k}" for k in range(1, n + 1))
    body = "\n".join(f"    s{k} = s{k} + {k}" for k in range(1, n + 1))
    chk = "\n".join(f"  if (s{k} /= {100 + 5 * k}) then\n    bad = bad + 1\n"
                    f"    if (first < 0) first = {k}\n  end if"
                    for k in range(1, n + 1))
    return f"""! {n} integer sum reductions on one OpenACC parallel
! loop (the kernel of the stress program scalars.reduction-acc-200, alone).
! Each s_k starts at 100 + k and adds k in each of 4 iterations, so it ends
! at 100 + 5k (OpenACC 3.4 §2.9.11; §2.11 p.76 l.2790-2792: a reduction
! clause on a combined construct implies a copy clause). Expected: bad= 0
program p
  implicit none
  integer :: ii, bad, first
{decl}
{init}
  !$acc parallel loop reduction(+: {red})
  do ii = 1, 4
{body}
  end do
  bad = 0
  first = -1
{chk}
  print '(a,i0,a,i0,a,i0,a,i0)', 'bad= ', bad, ' first= ', first, ' s1= ', s1, ' s{n}= ', s{n}
end program p
"""


def expected(e: int) -> int:
    q, r = divmod(2 ** e, 1009)
    return q * 508536 + sum((i * 642) % 1009 for i in range(1, r + 1))


def alloc(e: int, array: bool = True) -> str:
    if not array:
        return f"""! Control for alloc_{e}.f90: the same 2**{e}
! iterations and sum, without the array. Expected: s= {expected(e)}
program p
  implicit none
  integer(8) :: i, nn, s
  nn = 2_8**{e}
  s = 0
  !$omp target teams distribute parallel do reduction(+: s)
  do i = 1, nn
    s = s + mod(i * 642, 1009_8)
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 's= ', s
end program p
"""
    return f"""! Fill and reduce an integer(8) allocatable of 2**{e}
! elements on the device (the stress program runtime.alloc-omp at
! 2**{e}): integer(8) indices and extents, so no index overflows; 2**{e} * 8
! bytes on the host and on the device. Expected: s= {expected(e)} (the sum of
! mod(i*642, 1009), i = 1..2**{e}: 642 is invertible mod 1009, so each run of
! 1009 consecutive i adds 0 + 1 + ... + 1008 = 508536)
program p
  implicit none
  integer(8) :: i, nn, s
  integer(8), allocatable :: big(:)
  nn = 2_8**{e}
  s = 0
  allocate(big(nn))
  !$omp target enter data map(alloc: big)
  !$omp target teams distribute parallel do
  do i = 1, nn
    big(i) = mod(i * 642, 1009_8)
  end do
  !$omp end target teams distribute parallel do
  !$omp target teams distribute parallel do reduction(+: s)
  do i = 1, nn
    s = s + big(i)
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(delete: big)
  deallocate(big)
  print '(a,i0)', 's= ', s
end program p
"""


if __name__ == "__main__":
    for n in (8, 16, 24, 32, 40, 48, 56, 64):
        (HERE / f"red_c_{n}.c").write_text(red_c(n))
    for n in (25, 50, 75, 100, 125, 150, 175, 200):
        (HERE / f"red_acc_{n}.f90").write_text(red_acc(n))
    for e in (30, 31, 32):
        (HERE / f"alloc_{e}.f90").write_text(alloc(e))
    (HERE / "iter_32.f90").write_text(alloc(32, False))
