! # Finding (from the data/bench/fresh draft fresh-076): NVHPC loses contributions of a gang
!   worker collapse(2) reduction with a nested vector reduction
!
! - source: data/bench/fresh/fresh-076.f90 (NVIDIA developer forum topic 354721, the full program of the
!   2025-12-16 reply). The reporter's program has no data clause for sumA on the parallel
!   construct, which OpenACC 3.4 §2.6.2 p.42 l.1403-1409 forbids for a scalar in a loop reduction
!   whose access is exposed to a parent parallel construct; this reproducer adds copy(sumA) and sets
!   A = 1 so the sum is exact. With the reporter's sizes (1000 x 1000 x 100, 100 calls) the legal
!   form ends in CUDA_ERROR_ILLEGAL_ADDRESS (data/reports/fresh-drafts/d076-copy.f90)
! - compilers: NVHPC nvfortran 25.11 and 26.9, -acc=gpu -gpu=cc80 -O2, -gpu=mem:separate and
!   -gpu=mem:managed; A100
! - expected: pass 10000000.0. Each loop's reduction combines the private copies after the loop
!   with the original var (OpenACC 3.4 §2.9.11 p.71 l.2549-2555); a reduction spanning nested
!   loops carries the clause on each loop directive (l.2560-2562), as here; every A(i,j,k) is 1, so
!   the sum is m*n*o = 10^7 exactly in any order
! - actual: 9987000 to 9997000 (whole inner loops of 1000 lost; the count varies between runs), both
!   releases, both memory modes, 12 of 12 runs
! - control (same compiler): 10000000 with gang collapse(2) instead of gang worker collapse(2)
!   (data/reports/fresh-drafts/d076-c-gang.f90), with the inner loop seq (d076-c-seq.f90), or with
!   worker vector on the inner loop (d076-c-worker-vector.f90); the same nest at 64 x 64 x 4 is
!   correct (d076-exact-small.f90)
! - other families: CCE 19/20/21 print pass 10000000 on this program (MI300A HSA_XNACK 1 and 0;
!   MI250X); AFAR has no Fortran OpenACC
! - legality: legal by reading (copy(sumA) on the parallel construct; the reduction clause on both
!   loop directives of the nest)
! - evidence: results/fresh-drafts/wingtip/nv.jsonl, tuo2-q6.jsonl, tioga/tioga-b.jsonl (review)
module test_mod
contains
subroutine test(A, sumA)
  implicit none
  real(kind=8) :: A(:,:,:), sumA
  integer :: i, j, k
!$acc parallel copy(sumA)
!$acc loop gang worker collapse(2) reduction(+:sumA)
  do k = 1, size(A,3)
    do j = 1, size(A,2)
!$acc loop vector reduction(+:sumA)
      do i = 1, size(A,1)
        sumA = sumA + A(i,j,k)
      end do
    end do
  end do
!$acc end parallel
end subroutine test
end module test_mod

program main
  use test_mod
  implicit none
  integer, parameter :: m = 1000, n = 1000, o = 10
  real(kind=8) :: A(m,n,o), sumA
  A = 1.0d0
  sumA = 0.0d0
  call test(A, sumA)
  if (sumA == real(m, 8)*n*o) then
    print *, 'pass', sumA
  else
    print *, 'fail', sumA, ' expected', real(m, 8)*n*o
  end if
end program main
! site:
! title: nvfortran -acc: gang worker collapse(2) reduction with a nested vector reduction loses whole inner loops
! control: ../vendor/checks/src/nvhpc/control/nvhpc-acc-gang-worker-collapse-nested-vector-reduction-lost-control.f90 gang
! + collapse(2)
! + instead of
! + gang worker collapse(2)
! end site
