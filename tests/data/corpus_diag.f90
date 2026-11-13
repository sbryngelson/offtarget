! Excerpts copied verbatim from corpus/llvm
! flang/test/Semantics/OpenMP/device-constructs.f90 (an lit-diagnostic file:
! deliberate errors marked !ERROR); lines 27-38 and 147-152.
  !ERROR: At most one DEVICE clause can appear on TARGET directive
  !$omp target device(0) device(1)
  do i = 1, N
     a = 3.14d0
  enddo
  !$omp end target

  !ERROR: SCHEDULE clause is not allowed on TARGET directive
  !$omp target schedule(static)
  do i = 1, N
     a = 3.14d0
  enddo
  !ERROR: At least one of MAP, USE_DEVICE_ADDR, USE_DEVICE_PTR clauses must appear on TARGET DATA directive
  !$omp target data device(0)
  do i = 1, N
     a = 3.14d0
  enddo
  !$omp end target data
