! Fresh-070 legal form: ny0 and nyN in declare target (updated to
! the device after they are set), every array defined before use.
! Expected: sum 78.0 (85 ones; the boundary update zeroes 4 + 3 of them), then done
MODULE test

  IMPLICIT NONE

  integer :: nz, ny, ny0, nyN
  real(8), allocatable ::D2vmat(:, :, :)
  real(8), dimension(-2:2) :: v0bc, v0m1bc
  !$omp declare target(ny0, nyN)

CONTAINS

  !----------------- apply the boundary conditions --------------!
  PURE SUBROUTINE applybc_0(EQ, bc0, bc0m1)
    IMPLICIT NONE
    real(8), intent(inout) :: EQ(ny0:nyN + 2, -2:2)
    real(8), intent(in) :: bc0(-2:2), bc0m1(-2:2)
    EQ(1, -1:2) = EQ(1, -1:2) - EQ(1, -2)*bc0m1(-1:2)/bc0m1(-2)
    EQ(1, 0:2) = EQ(1, 0:2) - EQ(1, -1)*bc0(0:2)/bc0(-1)
    EQ(2, -1:1) = EQ(2, -1:1) - EQ(2, -2)*bc0(0:2)/bc0(-1)
  END SUBROUTINE applybc_0


  SUBROUTINE linsolve()
    IMPLICIT NONE
    integer :: iz

    !$omp target enter data map(to: v0bc, v0m1bc, D2vmat)
    !$omp target teams distribute parallel do shared(v0bc, v0m1bc, D2vmat, ny0, nyN)
    DO iz = -nz, nz
        CALL applybc_0(D2vmat(iz, :, :), v0bc, v0m1bc)
    END DO
    !$omp target exit data map(from: D2vmat)

  END SUBROUTINE linsolve

END MODULE test

PROGRAM foo
  USE test
  IMPLICIT NONE

    nz = 8
    ny = 16
    ny0 = 1
    nyN = ny - 1

    !$omp target update to(ny0, nyN)
    ALLOCATE(D2vmat(-nz:nz, ny0:nyN+2,-2:2))
    D2vmat = 1.0d0
    v0bc = 2.0d0
    v0m1bc = 4.0d0

    CALL linsolve()

    print *, 'sum', sum(d2vmat(0, :, :))
    print *, 'done'
END PROGRAM foo
