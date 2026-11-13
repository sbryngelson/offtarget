! Schedule(static, 4) on a parallel do in a target region:
! "iterations are divided into chunks of size chunk_size, and the chunks
! are assigned to the threads in the team in a round-robin fashion in the
! order of the thread number" (5.2 §11.5.3 p.252), so iteration i runs on
! thread mod((i - 1)/4, T). schedule(static) without a chunk size: "at
! most one chunk is distributed to each thread" (same page), so each
! thread's iterations are contiguous.
! Expected: 0 wrong, 0 second chunks. Observed (MI300A, HSA_XNACK 0 and 1,
! 3 runs each): AFAR flang, CCE 19, 20 and 21 ftn: 256 threads,
! tid(1:12) = 0 1 2 ... 11 for both loops (one iteration at a time,
! round-robin), 997 of 1000 iterations on the wrong thread, 744 second
! chunks. The C form (sched_repro.c in results/t27a/diag/d2, AMD clang)
! is correct: tid = 0 0 0 0 1 1 1 1 ...
program sched_repro
  use omp_lib
  implicit none
  integer, parameter :: m = 1000
  integer :: tid(m), tid2(m), nthr, i, bad, bad2
  tid = -1
  tid2 = -1
  nthr = -1
  !$omp target map(from: tid, tid2, nthr)
    !$omp parallel do schedule(static, 4)
      do i = 1, m
        if (i == 1) nthr = omp_get_num_threads()
        tid(i) = omp_get_thread_num()
      end do
    !$omp end parallel do
    !$omp parallel do schedule(static)
      do i = 1, m
        tid2(i) = omp_get_thread_num()
      end do
    !$omp end parallel do
  !$omp end target
  bad = 0
  do i = 1, m
    if (tid(i) /= mod((i - 1)/4, nthr)) bad = bad + 1
  end do
  ! static without chunk: at most one chunk (contiguous) per thread
  bad2 = 0
  do i = 2, m
    if (tid2(i) /= tid2(i - 1) .and. any(tid2(1:i - 1) == tid2(i))) bad2 = bad2 + 1
  end do
  print '(a,i0,a,12(1x,i0))', 'threads=', nthr, ' static,4 tid(1:12)=', tid(1:12)
  print '(a,12(1x,i0))', 'static tid(1:12)=', tid2(1:12)
  print '(a,i0,a,i0,a)', 'static,4 iterations on the wrong thread: ', bad, ' of ', m, ' (expected 0)'
  print '(a,i0,a)', 'static: iterations starting a second chunk of a thread: ', bad2, ' (expected 0)'
end program sched_repro
! site:
! title: ftn: schedule(static, 4) and schedule(static) on a parallel do in a target region deal iterations out one at a time
! control: ../vendor/checks/src/other/control/fortran-schedule-static-in-target-control.f90 schedule(static, 1) and its check
! + (iteration
! + i on
! + thread mod(i - 1, T)) instead of schedule(static, 4)
! end site
