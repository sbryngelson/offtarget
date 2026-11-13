! # CCE 21: a private array in a target loop, subscripted by a value read from device memory, reads its first element
!
! (found while reducing MFC's CCE 20 device-link crash: MFC's characteristic boundary kernels index
! private arrays with a declare target module array, `vel(dir_idx(1))`; a standalone form of that kernel gave
! a different answer on CCE 21 only). Compile: CCE `ftn -fopenmp -O2` (also -O0) after `module load cce/<v>
! craype-accel-amd-gfx942 rocm/<r>; module unload cray-mpich` (gfx90a on MI250X); AFAR `amdflang -fopenmp
! --offload-arch=gfx942`; NVHPC `nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate|managed`; run with
! OMP_TARGET_OFFLOAD=mandatory.
! Expected:
!   bad: mapped-subscript 0 declare-target-subscript 0 teams-distribute-parallel-do 0 teams-distribute 0
!   control-bad: firstprivate-subscript 0 computed-subscript 0 mapped-array 0
!
! Observed (2026-10-25):
! - CCE 21.0.3: `bad: mapped-subscript 64 declare-target-subscript 64 teams-distribute-parallel-do 64
!   teams-distribute 64` (every iteration reads v(1) = 10 instead of v(3) = 30), the control line all 0;
!   MI300A at HSA_XNACK 1 and 0, also at -O0; MI250X at HSA_XNACK 0.
! - CCE 19.0.0 and 20.0.2, AFAR 24.0.0git (drop 24.3.0): all 0 (MI300A both modes, MI250X).
! - NVHPC 25.11 and 26.9 (A100, separate and managed memory): all 0.
! Logs: data/reports/apps/.
! Same-compiler controls (in this program, CCE 21 correct): the same private array subscripted by a
! firstprivate scalar (k = 3), or by a subscript computed from the loop variable, and a mapped (not private)
! array subscripted by the same mapped element s(3). Without a loop construct (a target region whose body
! reads v(s(3))) CCE 21 is also correct (controls/private-array-subscript-probes.f90, z4). So the failing combination is a private
! array of a target loop (parallel do or distribute) and a subscript loaded from a mapped or declare target
! array.
!
! Basis (OpenMP 5.2):
! - §5.4.3 p.111 l.9-12: "The private clause specifies that its list items are to be privatized according
!   to Section 5.3. Each task or SIMD lane that references a list item in the construct receives only one new
!   list item, unless the construct has one or more associated loops and an order clause that specifies
!   concurrent is also present."
! - §5.3 p.105 l.21-30: "Inside the construct, all references to the original list item are replaced by
!   references to a new list item received by the task or SIMD lane. If the construct has one or more
!   associated loops then, within the same logical iteration of the loops, the same new list item replaces
!   all references to the original list item." Each iteration assigns v(1:3) = 10, 20, 30 and then reads
!   v(3) through the subscript s(3) = d(3) = 3, so the result is 30.
! - s is mapped `to` (§5.8.3); d is a declare target module array (§7.8.1) made consistent by `target update
!   to(d)` (§13.9 p.289 l.12-13: "The target update directive makes the corresponding list items in the
!   device data environment consistent with their original list items").
! Race-free: v is private, every z array element is written by one iteration, s and d are only read. Legality
! was read against the spec; no compiler under test, gfortran or gcc is a legality witness.
!
! MFC: its kernels read private arrays through dir_idx (a declare target module array), for example
! `lambda(1) = vel(dir_idx(1)) - c` in m_cbc; on CCE 21 they would read the wrong component (MFC does not
! link on CCE 21). Workaround: copy the subscript to
! a firstprivate scalar outside the loop, or keep such arrays shared (mapped).
module pas_m
  implicit none
  integer :: d(3)
  !$omp declare target (d)
end module pas_m
program private_array_loaded_subscript
  use pas_m
  implicit none
  integer, parameter :: n = 64
  integer :: zb(n), zc(n), zt(n), za(n), zd(n), zn(n), zw(n), v(3), w(3), s(3), k, r
  k = 3
  s = [1, 2, 3]
  d = [1, 2, 3]
  !$omp target update to(d)
  zb = -1; zc = -1; zt = -1; za = -1; zd = -1; zn = -1; zw = -1
  w = [10, 20, 30]
  ! the subscript is an element of a mapped array
  !$omp target parallel do map(from: zb) map(to: s) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zb(r) = v(s(3))
  end do
  ! the subscript is an element of a declare target array
  !$omp target parallel do map(from: zc) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zc(r) = v(d(3))
  end do
  ! the same on target teams distribute parallel do
  !$omp target teams distribute parallel do map(from: zt) map(to: s) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zt(r) = v(s(3))
  end do
  ! same-compiler controls: a firstprivate scalar subscript, a subscript computed from r
  !$omp target parallel do map(from: za) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    za(r) = v(k)
  end do
  !$omp target parallel do map(from: zd) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zd(r) = v(mod(r - 1, 3) + 1)
  end do
  ! the same on target teams distribute (no parallel construct)
  !$omp target teams distribute map(from: zn) map(to: s) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zn(r) = v(s(3))
  end do
  ! same-compiler control: a mapped (not private) array with the mapped subscript
  !$omp target parallel do map(from: zw) map(to: s, w)
  do r = 1, n
    zw(r) = w(s(3))
  end do
  print '(a,i0,a,i0,a,i0,a,i0)', 'bad: mapped-subscript ', count(zb /= 30), ' declare-target-subscript ', &
    count(zc /= 30), ' teams-distribute-parallel-do ', count(zt /= 30), ' teams-distribute ', count(zn /= 30)
  print '(a,i0,a,i0,a,i0)', 'control-bad: firstprivate-subscript ', count(za /= 30), ' computed-subscript ', &
    count([(zd(r) /= 10*(mod(r - 1, 3) + 1), r = 1, n)]), ' mapped-array ', count(zw /= 30)
end program private_array_loaded_subscript
! site:
! title: ftn: a private array subscripted by an element of a mapped or declare target array reads the wrong element in a target loop
! control: ../vendor/checks/src/cce/control/cce21-private-array-loaded-subscript-wrong-control.f90 in the first region, the constant
! + subscript
! + v(3) instead of v(s(3))
! end site
