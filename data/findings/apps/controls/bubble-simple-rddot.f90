! Docs/findings/apps/cce21-device-link-agpr-copy-mfma-assert.f90: CONTROL: the Gilmore acceleration f_rddot replaced by a
! one-line expression.
! Expected and observed on CCE 19, 20, 21 and AFAR (MI300A XNACK 1 and 0, MI250X): builds, bad= 0.
module glob
  implicit none
  integer, parameter :: wp = kind(1.d0)
  real(wp), parameter :: pi = 3.141592653589793_wp, verysmall = 1.e-12_wp, dflt_real = -1.e6_wp
  type scalar_field
  end type scalar_field
  real(wp) :: Re_inv, Web, Ca, Eu, gam, gam_m, phi_vg, phi_gv, Pe_c, Tw, pv, gam_v, gam_g, M_v, M_g, R_v, R_g
  real(wp) :: adap_dt_tol, dt
  logical :: polytropic, bubbles_lagrange, bubbles_euler, mpp_lim, lag_pressure_force
  integer :: thermal, bubble_model, adap_dt_max_iters, lag_vel_model, fd_order, num_dims, sys_size
  real(wp) :: pb0(4), mass_g0(4), mass_v0(4), Pe_T(4), k_v(4), k_g(4), Re_trans_T(4), Re_trans_c(4), R0(4)
!$omp declare target (Re_inv, Web, Ca, Eu, gam, Tw, pv, gam_v, gam_g, R_v, R_g)
!$omp declare target (adap_dt_tol, dt, bubbles_lagrange)
!$omp declare target (thermal, adap_dt_max_iters, sys_size)
contains
  logical function f_approx_equal(a, b)
    real(wp), intent(in) :: a, b
    f_approx_equal = abs(a - b) <= 1.e-10_wp*max(abs(a), abs(b), 1.e-30_wp)
  end function f_approx_equal
end module glob
module bel
  implicit none
contains
end module bel
module m_bubbles
  use glob
  implicit none
contains
    function f_rddot(fRho, fP, fR, fV, fR0, fpb, fpbdot, alf, fntait, fBtait, f_bub_adv_src, f_divu, fCson)
        real(wp), intent(in) :: fRho, fP, fR, fV, fR0, fpb, fpbdot, alf
        real(wp), intent(in) :: fntait, fBtait, f_bub_adv_src, f_divu
        real(wp), intent(in) :: fCson
        real(wp)             :: fCpbw, fCpinf, fCpinf_dot, fH, fHdot, c_gas, c_liquid
        real(wp)             :: f_rddot
            fCpbw = f_cpbw(fR0, fR, fV, fpb)
            f_rddot = (fCpbw - fP + Eu)/(fRho*fR) + 0._wp*(fpbdot + alf + fntait + fBtait + f_bub_adv_src + f_divu + fCson)
    end function f_rddot
    function f_cpbw(fR0, fR, fV, fpb)
        real(wp), intent(in) :: fR0, fR, fV, fpb
        real(wp)             :: f_cpbw
            f_cpbw = (Ca + 2._wp/Web/fR0)*((fR0/fR)**(3._wp*gam)) - Ca - 4._wp*Re_inv*fV/fR - 2._wp/(fR*Web)
    end function f_cpbw
    function f_H(fCpbw, fCpinf, fntait, fBtait)
        real(wp), intent(in) :: fCpbw, fCpinf, fntait, fBtait
        real(wp)             :: tmp1, tmp2, tmp3
        real(wp)             :: f_H
        tmp1 = (fntait - 1._wp)/fntait
        tmp2 = (fCpbw/(1._wp + fBtait) + 1._wp)**tmp1
        tmp3 = (fCpinf/(1._wp + fBtait) + 1._wp)**tmp1
        f_H = (tmp2 - tmp3)*fntait*(1._wp + fBtait)/(fntait - 1._wp)
    end function f_H
    function f_cgas(fCpinf, fntait, fBtait, fH)
        real(wp), intent(in) :: fCpinf, fntait, fBtait, fH
        real(wp)             :: tmp
        real(wp)             :: f_cgas
        tmp = (fCpinf/(1._wp + fBtait) + 1._wp)**((fntait - 1._wp)/fntait)
        f_cgas = sqrt(tmp + (fntait - 1._wp)*fH)
    end function f_cgas
    function f_cpinfdot(fRho, fP, falf, fntait, fBtait, advsrc, divu)
        real(wp), intent(in) :: fRho, fP, falf, fntait, fBtait, advsrc, divu
        real(wp)             :: c2_liquid
        real(wp)             :: f_cpinfdot
            c2_liquid = fntait*(fP + fBtait)/fRho
        f_cpinfdot = fRho*c2_liquid*(advsrc - divu)
    end function f_cpinfdot
    function f_Hdot(fCpbw, fCpinf, fCpinf_dot, fntait, fBtait, fR, fV, fR0, fpbdot)
        real(wp), intent(in) :: fCpbw, fCpinf, fCpinf_dot, fntait, fBtait
        real(wp), intent(in) :: fR, fV, fR0, fpbdot
        real(wp)             :: tmp1, tmp2
        real(wp)             :: f_Hdot
            tmp1 = fpbdot
        tmp2 = (2._wp/Web + 4._wp*Re_inv*fV)*fV/(fR**2._wp)
        f_Hdot = (fCpbw/(1._wp + fBtait) + 1._wp)**(-1._wp/fntait)*(tmp1 + tmp2) - (fCpinf/(1._wp + fBtait) + 1._wp) &
                  & **(-1._wp/fntait)*fCpinf_dot
    end function f_Hdot
    function f_rddot_G(fCpbw, fR, fV, fH, fHdot, fcgas, fntait, fBtait)
        real(wp), intent(in) :: fCpbw, fR, fV, fH, fHdot
        real(wp), intent(in) :: fcgas, fntait, fBtait
        real(wp)             :: tmp1, tmp2, tmp3
        real(wp)             :: f_rddot_G
        tmp1 = fV/fcgas
        tmp2 = 1._wp + 4._wp*Re_inv/fcgas/fR*(fCpbw/(1._wp + fBtait) + 1._wp)**(-1._wp/fntait)
        tmp3 = 1.5_wp*fV**2._wp*(tmp1/3._wp - 1._wp) + fH*(1._wp + tmp1) + fR*fHdot*(1._wp - tmp1)/fcgas
        f_rddot_G = tmp3/(fR*(1._wp - tmp1)*tmp2)
    end function f_rddot_G
    subroutine s_vflux(fR, fV, fpb, fmass_v, iR0, vflux, fmass_g, fbeta_c, fR_m, fgamma_m, fchi_vw, frho_mw)
        real(wp), intent(in)            :: fR
        real(wp), intent(in)            :: fV
        real(wp), intent(in)            :: fpb
        real(wp), intent(in)            :: fmass_v
        integer, intent(in)             :: iR0
        real(wp), intent(out)           :: vflux
        real(wp), intent(in), optional  :: fmass_g, fbeta_c
        real(wp), intent(out), optional :: fR_m, fgamma_m
        real(wp), intent(in), optional  :: fchi_vw, frho_mw  !< Per-thread bubble-wall scratch (Euler-Euler path)
        real(wp)                        :: conc_v
        if (thermal == 3) then  ! transfer
                conc_v = fmass_v/(fmass_v + fmass_g)
                fR_m = (fmass_g*R_g + fmass_v*R_v)
                fgamma_m = conc_v*gam_v + (1._wp - conc_v)*gam_g
            vflux = pv*fV/(R_v*Tw)
        end if
    end subroutine s_vflux
    function f_bpres_dot(fvflux, fR, fV, fpb, fmass_v, iR0, fbeta_t, fR_m, fgamma_m, fk_mw)
        real(wp), intent(in)           :: fvflux
        real(wp), intent(in)           :: fR
        real(wp), intent(in)           :: fV
        real(wp), intent(in)           :: fpb
        real(wp), intent(in)           :: fmass_v
        integer, intent(in)            :: iR0
        real(wp), intent(in), optional :: fbeta_t, fR_m, fgamma_m
        real(wp), intent(in), optional :: fk_mw  !< Per-thread bubble-wall conductivity scratch (Euler-Euler path)
        real(wp)                       :: T_bar
        real(wp)                       :: grad_T
        real(wp)                       :: f_bpres_dot
        real(wp)                       :: heatflux
                T_bar = fpb*(4._wp/3._wp*pi*fR**3._wp)/fR_m
                grad_T = -fbeta_t*(T_bar - Tw)
                heatflux = (fgamma_m - 1._wp)/fgamma_m*grad_T/fR
                f_bpres_dot = 3._wp*fgamma_m*(-fV*fpb + fvflux*R_v*Tw + heatflux)/fR
    end function f_bpres_dot
    function f_advance_step(fRho, fP, fR, fV, fR0, fpb, fpbdot, alf, fntait, fBtait, f_bub_adv_src, f_divu, bub_id, fmass_v, &
                            & fmass_g, fbeta_c, fbeta_t, fCson, fRe, fPos, fVel, cell, q_prim_vf) result(adap_dt_stop)
        real(wp), intent(inout)                                       :: fR, fV, fpb, fmass_v
        real(wp), intent(in)                                          :: fRho, fP, fR0, fpbdot, alf
        real(wp), intent(in)                                          :: fntait, fBtait, f_bub_adv_src, f_divu
        integer, intent(in)                                           :: bub_id
        real(wp), intent(in)                                          :: fmass_g, fbeta_c, fbeta_t, fCson
        real(wp), intent(inout), dimension(3), optional               :: fPos, fVel
        real(wp), intent(in), optional                                :: fRe
        integer, intent(in), dimension(3), optional                   :: cell
        type(scalar_field), intent(in), dimension(sys_size), optional :: q_prim_vf
        real(wp), dimension(5)                                        :: err    !< Error estimates for adaptive time stepping
        real(wp)                                                      :: t_new  !< Updated time step size
        real(wp)                                                      :: h0, h  !< Time step size
        real(wp), dimension(4) :: myR_tmp1, myV_tmp1, myR_tmp2, myV_tmp2
        real(wp), dimension(4) :: myPb_tmp1, myMv_tmp1, myPb_tmp2, myMv_tmp2  !< Gas pressure and vapor mass for the inner loop (EL)
        real(wp)               :: fR2, fV2, fpb2, fmass_v2, f_bTemp
        integer                :: adap_dt_stop
        integer                :: l, iter_count
        h0 = 1.e-5_wp*dt
        h = h0
        t_new = 0._wp
        iter_count = 0
        adap_dt_stop = 0
        do
            do while (iter_count < adap_dt_max_iters)
                iter_count = iter_count + 1
                call s_advance_substep(err(1), fRho, fP, fR, fV, fR0, fpb, fpbdot, alf, fntait, fBtait, f_bub_adv_src, f_divu, &
                                       & bub_id, fmass_v, fmass_g, fbeta_c, fbeta_t, fCson, h, myR_tmp1, myV_tmp1, myPb_tmp1, &
                                       & myMv_tmp1)
                if (err(1) > adap_dt_tol) then
                    h = 0.25_wp*h
                    cycle
                end if
                call s_advance_substep(err(2), fRho, fP, fR, fV, fR0, fpb, fpbdot, alf, fntait, fBtait, f_bub_adv_src, f_divu, &
                                       & bub_id, fmass_v, fmass_g, fbeta_c, fbeta_t, fCson, 0.5_wp*h, myR_tmp2, myV_tmp2, &
                                       & myPb_tmp2, myMv_tmp2)
                if (err(2) > adap_dt_tol) then
                    h = 0.25_wp*h
                    cycle
                end if
                fR2 = myR_tmp2(4); fV2 = myV_tmp2(4)
                fpb2 = myPb_tmp2(4); fmass_v2 = myMv_tmp2(4)
                call s_advance_substep(err(3), fRho, fP, fR2, fV2, fR0, fpb2, fpbdot, alf, fntait, fBtait, f_bub_adv_src, f_divu, &
                                       & bub_id, fmass_v2, fmass_g, fbeta_c, fbeta_t, fCson, 0.5_wp*h, myR_tmp2, myV_tmp2, &
                                       & myPb_tmp2, myMv_tmp2)
                err(4) = abs((myR_tmp1(4) - myR_tmp2(4))/myR_tmp1(4))
                err(5) = abs((myV_tmp1(4) - myV_tmp2(4))/myV_tmp1(4))
                if ((err(1) <= adap_dt_tol) .and. (err(2) <= adap_dt_tol) .and. (err(3) <= adap_dt_tol) .and. (err(4) &
                    & <= adap_dt_tol) .and. (err(5) <= adap_dt_tol) .and. myR_tmp1(4) > 0._wp) then
                    t_new = t_new + h
                    fR = myR_tmp1(4); fV = myV_tmp1(4); fpb = myPb_tmp1(4); fmass_v = myMv_tmp1(4)
                    h = h*min(2._wp, max(0.5_wp, (adap_dt_tol/err(1))**(1._wp/3._wp)))
                    exit
                end if
            end do
            if (f_approx_equal(t_new, 0.5_wp*dt) .or. iter_count >= adap_dt_max_iters) exit
        end do
        if (iter_count >= adap_dt_max_iters) adap_dt_stop = 1
    end function f_advance_step
    subroutine s_advance_substep(err, fRho, fP, fR, fV, fR0, fpb, fpbdot, alf, fntait, fBtait, f_bub_adv_src, f_divu, bub_id, &
                                 & fmass_v, fmass_g, fbeta_c, fbeta_t, fCson, h, myR_tmp, myV_tmp, myPb_tmp, myMv_tmp)
        real(wp), intent(out)               :: err
        real(wp), intent(in)                :: fRho, fP, fR, fV, fR0, fpb, fpbdot, alf
        real(wp), intent(in)                :: fntait, fBtait, f_bub_adv_src, f_divu, h
        integer, intent(in)                 :: bub_id
        real(wp), intent(in)                :: fmass_v, fmass_g, fbeta_c, fbeta_t, fCson
        real(wp), dimension(4), intent(out) :: myR_tmp, myV_tmp, myPb_tmp, myMv_tmp
        real(wp), dimension(4)              :: myA_tmp, mydPbdt_tmp, mydMvdt_tmp
        real(wp)                            :: err_R, err_V
        myR_tmp(1) = fR
        myV_tmp(1) = fV
        if (bubbles_lagrange) then
            myPb_tmp(1) = fpb
            myMv_tmp(1) = fmass_v
            call s_advance_EL(myR_tmp(1), myV_tmp(1), myPb_tmp(1), myMv_tmp(1), bub_id, fmass_g, fbeta_c, fbeta_t, &
                              & mydPbdt_tmp(1), mydMvdt_tmp(1))
        end if
        myA_tmp(1) = f_rddot(fRho, fP, myR_tmp(1), myV_tmp(1), fR0, myPb_tmp(1), mydPbdt_tmp(1), alf, fntait, fBtait, &
                & f_bub_adv_src, f_divu, fCson)
        myR_tmp(2) = myR_tmp(1) + h*myV_tmp(1)
        if (myR_tmp(2) < 0._wp) then
            err = adap_dt_tol + 1._wp; return
        end if
        myV_tmp(2) = myV_tmp(1) + h*myA_tmp(1)
            myPb_tmp(2) = myPb_tmp(1) + h*mydPbdt_tmp(1)
            myMv_tmp(2) = myMv_tmp(1) + h*mydMvdt_tmp(1)
            call s_advance_EL(myR_tmp(2), myV_tmp(2), myPb_tmp(2), myMv_tmp(2), bub_id, fmass_g, fbeta_c, fbeta_t, &
                              & mydPbdt_tmp(2), mydMvdt_tmp(2))
        myA_tmp(2) = f_rddot(fRho, fP, myR_tmp(2), myV_tmp(2), fR0, myPb_tmp(2), mydPbdt_tmp(2), alf, fntait, fBtait, &
                & f_bub_adv_src, f_divu, fCson)
        myR_tmp(3) = myR_tmp(1) + (h/4._wp)*(myV_tmp(1) + myV_tmp(2))
        myV_tmp(3) = myV_tmp(1) + (h/4._wp)*(myA_tmp(1) + myA_tmp(2))
            myPb_tmp(3) = myPb_tmp(1) + (h/4._wp)*(mydPbdt_tmp(1) + mydPbdt_tmp(2))
            myMv_tmp(3) = myMv_tmp(1) + (h/4._wp)*(mydMvdt_tmp(1) + mydMvdt_tmp(2))
            call s_advance_EL(myR_tmp(3), myV_tmp(3), myPb_tmp(3), myMv_tmp(3), bub_id, fmass_g, fbeta_c, fbeta_t, &
                              & mydPbdt_tmp(3), mydMvdt_tmp(3))
        myA_tmp(3) = f_rddot(fRho, fP, myR_tmp(3), myV_tmp(3), fR0, myPb_tmp(3), mydPbdt_tmp(3), alf, fntait, fBtait, &
                & f_bub_adv_src, f_divu, fCson)
        myR_tmp(4) = myR_tmp(1) + (h/6._wp)*(myV_tmp(1) + myV_tmp(2) + 4._wp*myV_tmp(3))
        myV_tmp(4) = myV_tmp(1) + (h/6._wp)*(myA_tmp(1) + myA_tmp(2) + 4._wp*myA_tmp(3))
            myPb_tmp(4) = myPb_tmp(1) + (h/6._wp)*(mydPbdt_tmp(1) + mydPbdt_tmp(2) + 4._wp*mydPbdt_tmp(3))
            myMv_tmp(4) = myMv_tmp(1) + (h/6._wp)*(mydMvdt_tmp(1) + mydMvdt_tmp(2) + 4._wp*mydMvdt_tmp(3))
            call s_advance_EL(myR_tmp(4), myV_tmp(4), myPb_tmp(4), myMv_tmp(4), bub_id, fmass_g, fbeta_c, fbeta_t, &
                              & mydPbdt_tmp(4), mydMvdt_tmp(4))
        myA_tmp(4) = f_rddot(fRho, fP, myR_tmp(4), myV_tmp(4), fR0, myPb_tmp(4), mydPbdt_tmp(4), alf, fntait, fBtait, &
                & f_bub_adv_src, f_divu, fCson)
        err_R = (-5._wp*h/24._wp)*(myV_tmp(2) + myV_tmp(3) - 2._wp*myV_tmp(4))/max(abs(myR_tmp(1)), abs(myR_tmp(4)))
        err_V = (-5._wp*h/24._wp)*(myA_tmp(2) + myA_tmp(3) - 2._wp*myA_tmp(4))/max(abs(myV_tmp(1)), abs(myV_tmp(4)))
        err = sqrt((err_R**2._wp + err_V**2._wp)/2._wp)
    end subroutine s_advance_substep
    subroutine s_advance_EL(fR_tmp, fV_tmp, fPb_tmp, fMv_tmp, bub_id, fmass_g, fbeta_c, fbeta_t, fdPbdt_tmp, advance_EL)
        real(wp), intent(in)    :: fR_tmp, fV_tmp, fPb_tmp, fMv_tmp
        real(wp), intent(in)    :: fmass_g, fbeta_c, fbeta_t
        integer, intent(in)     :: bub_id
        real(wp), intent(inout) :: fdPbdt_tmp
        real(wp), intent(out)   :: advance_EL
        real(wp)                :: fVapFlux, myR_m, mygamma_m
        call s_vflux(fR_tmp, fV_tmp, fPb_tmp, fMv_tmp, bub_id, fVapFlux, fmass_g, fbeta_c, myR_m, mygamma_m)
        fdPbdt_tmp = f_bpres_dot(fVapFlux, fR_tmp, fV_tmp, fPb_tmp, fMv_tmp, bub_id, fbeta_t, myR_m, mygamma_m)
        advance_EL = 4._wp*pi*fR_tmp**2._wp*fVapFlux
    end subroutine s_advance_EL
end module m_bubbles
program cce21_agpr_copy_mfma
  use glob
  use m_bubbles
  implicit none
  integer, parameter :: n = 256
  real(wp) :: rr(n), vv(n), pb(n), mv(n), adv(n), divu(n), rr_h(n), vv_h(n), pb_h(n), mv_h(n)
  integer :: st(n), st_h(n), k, bad, dmBub_id
  real(wp) :: myRho, myP, alf, n_tait, B_tait, pbdot, dmMass_n, dmBeta_c, dmBeta_t, dmCson
  Re_inv = 1.e-3_wp; Web = 10._wp; Ca = 1._wp; Eu = 1._wp; gam = 1.4_wp; Tw = 1._wp; pv = 2.3e-2_wp
  gam_v = 1.33_wp; gam_g = 1.4_wp; R_v = 461._wp; R_g = 287._wp
  adap_dt_tol = 1.e-4_wp; dt = 1.e-3_wp; bubbles_lagrange = .true.; thermal = 3; adap_dt_max_iters = 100
  sys_size = 5; R0 = 1._wp
  !$omp target update to(Re_inv, Web, Ca, Eu, gam, Tw, pv, gam_v, gam_g, R_v, R_g)
  !$omp target update to(adap_dt_tol, dt, bubbles_lagrange, thermal, adap_dt_max_iters, sys_size)
  do k = 1, n
    rr(k) = 1._wp + 1.e-3_wp*k; vv(k) = 1.e-2_wp*sin(1._wp*k); pb(k) = 1._wp + 1.e-3_wp*k; mv(k) = 1.e-3_wp
    adv(k) = 0._wp; divu(k) = 0._wp
  end do
  rr_h = rr; vv_h = vv; pb_h = pb; mv_h = mv
  myRho = 1._wp; myP = 1.1_wp; alf = 0.1_wp; n_tait = 7.1_wp; B_tait = 3.e3_wp; pbdot = 0._wp
  dmBub_id = 1; dmMass_n = 1.e-2_wp; dmBeta_c = 1._wp; dmBeta_t = 1.e-3_wp; dmCson = 1._wp
  !$omp target teams distribute parallel do map(tofrom: rr, vv, pb, mv) map(to: adv, divu, R0) map(from: st)
  do k = 1, n
    st(k) = f_advance_step(myRho, myP, rr(k), vv(k), R0(1), pb(k), pbdot, alf, n_tait, B_tait, adv(k), divu(k), &
                           dmBub_id, mv(k), dmMass_n, dmBeta_c, dmBeta_t, dmCson)
  end do
  !$omp end target teams distribute parallel do
  do k = 1, n
    st_h(k) = f_advance_step(myRho, myP, rr_h(k), vv_h(k), R0(1), pb_h(k), pbdot, alf, n_tait, B_tait, adv(k), divu(k), &
                             dmBub_id, mv_h(k), dmMass_n, dmBeta_c, dmBeta_t, dmCson)
  end do
  bad = 0
  do k = 1, n
    if (st(k) /= st_h(k) .or. abs(rr(k) - rr_h(k)) > 1.e-9_wp*abs(rr_h(k))) bad = bad + 1
  end do
  print '(a,i0,a,i0,a,f10.6)', 'bad= ', bad, ' stops= ', count(st_h /= 0), ' R(1)= ', rr_h(1)
end program cce21_agpr_copy_mfma
