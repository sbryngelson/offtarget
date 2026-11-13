module m_bubbles_EE
    use m_bubbles
    real(wp), allocatable, dimension(:,:,:)   :: bub_adv_src
contains
    impure subroutine s_compute_bubble_EE_source(q_cons_vf, q_prim_vf, rhs_vf, divu_in)
        type(scalar_field), intent(in) :: divu_in  !< matrix for div(u)
        real(wp) :: pb_local, mv_local, vflux, pbdot
        real(wp) :: n_tait, B_tait, qv_bub
        real(wp) :: myR, myV, alf, myP, myRho, R2Vav, R3
        integer  :: i, j, k, l, q, ii               !< Loop variables
        integer  :: dmBub_id                        !< Dummy variables for unified subgrid bubble subroutines
        real(wp) :: dmMass_v, dmMass_n, dmBeta_c, dmBeta_t, dmCson
!$omp target teams distribute parallel do !$omp& !$omp& !$omp& !$omp& !$omp& !$omp& !$omp& !$omp&
            do k = 0, n
                                adap_dt_stop = f_advance_step(myRho, myP, myR, myV, R0(q), pb_local, pbdot, alf, n_tait, B_tait, &
                                                              & bub_adv_src(j, k, l), divu_in%sf(j, k, l), dmBub_id, dmMass_v, &
                                                              & dmMass_n, dmBeta_c, dmBeta_t, dmCson)
            end do
!$omp end target teams distribute parallel do
    end subroutine s_compute_bubble_EE_source
end module m_bubbles_EE
