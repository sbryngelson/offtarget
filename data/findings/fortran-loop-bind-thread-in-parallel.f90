! loop bind(thread) in a parallel region in a target region: the binding
! region is not defined and the binding thread set is the encountering
! thread (5.2 §11.7.1 p.257-258), so every thread of the team runs all n
! logical iterations ("Each logical iteration is executed once per
! instance of the loop region that is encountered by exactly one thread
! that is a member of the binding thread set", 5.2 §11.7 p.257). Each
! iteration writes its own element hit(i, thread + 1): no data race even
! though the iterations may execute concurrently.
! Expected: every thread ran all 64 iterations (0 short).
! Observed (MI300A, HSA_XNACK 0 and 1, 3 runs each): AFAR flang: 256
! threads, 1 iteration each for threads 0-3 (the team shares the
! iterations, as bind(parallel) would); CCE 19, 20, 21 ftn: 37-38, 1, 1, 1
! at HSA_XNACK=1 and 1 or 2 per thread at HSA_XNACK=0; all 256 threads
! short. The C form (AMD clang) is correct: 64 per thread.
! : on CCE the same loop without the loop
! directive fails too, and the program is correct at -O0: CCE's failure is
! the sequential-loop defect of cce19-target-parallel-guarded-loop.f90, not
! a bind(thread) defect. On AFAR it is a bind(thread) defect.
program bind_thread_repro
  use omp_lib
  implicit none
  integer, parameter :: n = 64
  integer :: hit(n, 1024), nthr, tid, i, k, short
  hit = 0
  nthr = -1
  !$omp target map(tofrom: hit, nthr)
    !$omp parallel private(tid)
      tid = omp_get_thread_num()
      if (tid == 0) nthr = omp_get_num_threads()
      !$omp loop bind(thread)
        do i = 1, n
          if (tid < 1024) hit(i, tid + 1) = hit(i, tid + 1) + 1
        end do
      !$omp end loop
    !$omp end parallel
  !$omp end target
  short = 0
  do k = 1, min(nthr, 1024)
    if (sum(hit(:, k)) /= n) short = short + 1
  end do
  print '(a,i0,a,4(1x,i0))', 'threads=', nthr, ' iterations run by threads 0-3:', &
    (sum(hit(:, k)), k = 1, 4)
  print '(a,i0,a)', 'threads that did not run all 64 iterations: ', short, ' (expected 0)'
end program bind_thread_repro
! site:
! title: ftn -fopenmp: a sequential DO loop executed by one thread of a target parallel region runs only some of its iterations
! + (-O2)
! control: ../vendor/checks/src/other/control/fortran-loop-bind-thread-in-parallel-control.f90 the loop directive removed (each
! + thread
! + runs a
! + plain DO loop)
! same_as: cce19-target-parallel-guarded-loop
! end site
