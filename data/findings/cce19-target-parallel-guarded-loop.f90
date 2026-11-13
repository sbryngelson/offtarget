program t
  use omp_lib, only: omp_get_thread_num
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: a(:), b(:)
  integer :: ref(n), i, nbad
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i; b(i) = 0; ref(i) = 2*i + 1
  end do
  !$omp target parallel map(to: a) map(from: b) 
    if (omp_get_thread_num() == 0) then
      do i = 1, n
        b(i) = 2*a(i) + 1
      end do
    end if
  !$omp end target parallel
  nbad = count(b /= ref)
  print *, 'base_cond bad=', nbad
end program
! site:
! title: ftn -fopenmp: a sequential DO loop executed by one thread of a target parallel region runs only some of its iterations
! + (-O2)
! control: ../vendor/checks/src/cce/control/cce19-target-parallel-guarded-loop-control.f90 compiled at -O0 instead of -O2 (-O0)
! end site
! spec (requirement): Every thread of the team created by a parallel construct executes the region, and each thread
!   may follow a different path of statements.
! "Each thread can execute a path of statements that is different from that of the other threads." (5.2 §10.1 p.223
!   l.27-28)
! spec (requirement): The thread with thread number zero is the primary thread and takes part in executing the region
!   like every other thread.
! "All threads in the new team, including the primary thread, execute the region." (5.2 §10.1 p.223 l.16-17)
! spec (this program): Only thread 0 enters the guarded branch and runs the sequential DO loop of 64 iterations, so
!   base-language semantics require all 64 elements of b to be written; the spec adds no rule that cuts a sequential
!   loop short. At -O2 the compiler runs only some of the iterations.
