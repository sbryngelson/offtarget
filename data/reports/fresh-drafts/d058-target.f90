! Fresh-058 variant: A = Z in a plain target region (no loop).
! Expected: 7.
MODULE GLOBALS
   IMPLICIT NONE
   REAL :: Z
   REAL, ALLOCATABLE, DIMENSION(:)::A

END MODULE GLOBALS

MODULE RECON
   USE GLOBALS

   IMPLICIT NONE

CONTAINS

   SUBROUTINE CRASH_REPRO()

      IMPLICIT NONE
      INTEGER::II

      ALLOCATE (A(10))
      Z = 7

      !$OMP target
         A = Z;
      !$OMP end target

      PRINT *, A(1)

   END SUBROUTINE CRASH_REPRO

END MODULE RECON

PROGRAM compilerCrashTest

   USE RECON
   IMPLICIT NONE

   CALL CRASH_REPRO()

END PROGRAM compilerCrashTest
