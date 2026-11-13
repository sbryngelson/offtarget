! 25 integer sum reductions on one OpenACC parallel
! loop (the kernel of the stress program scalars.reduction-acc-200, alone).
! Each s_k starts at 100 + k and adds k in each of 4 iterations, so it ends
! at 100 + 5k (OpenACC 3.4 §2.9.11; §2.11 p.76 l.2790-2792: a reduction
! clause on a combined construct implies a copy clause). Expected: bad= 0
program p
  implicit none
  integer :: ii, bad, first
  integer :: s1, s2, s3, s4, s5, s6, s7, s8, s9, s10
  integer :: s11, s12, s13, s14, s15, s16, s17, s18, s19, s20
  integer :: s21, s22, s23, s24, s25
  s1 = 101
  s2 = 102
  s3 = 103
  s4 = 104
  s5 = 105
  s6 = 106
  s7 = 107
  s8 = 108
  s9 = 109
  s10 = 110
  s11 = 111
  s12 = 112
  s13 = 113
  s14 = 114
  s15 = 115
  s16 = 116
  s17 = 117
  s18 = 118
  s19 = 119
  s20 = 120
  s21 = 121
  s22 = 122
  s23 = 123
  s24 = 124
  s25 = 125
  !$acc parallel loop reduction(+: s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, &
  !$acc& s11, s12, s13, s14, s15, s16, s17, s18, s19, s20, &
  !$acc& s21, s22, s23, s24, s25)
  do ii = 1, 4
    s1 = s1 + 1
    s2 = s2 + 2
    s3 = s3 + 3
    s4 = s4 + 4
    s5 = s5 + 5
    s6 = s6 + 6
    s7 = s7 + 7
    s8 = s8 + 8
    s9 = s9 + 9
    s10 = s10 + 10
    s11 = s11 + 11
    s12 = s12 + 12
    s13 = s13 + 13
    s14 = s14 + 14
    s15 = s15 + 15
    s16 = s16 + 16
    s17 = s17 + 17
    s18 = s18 + 18
    s19 = s19 + 19
    s20 = s20 + 20
    s21 = s21 + 21
    s22 = s22 + 22
    s23 = s23 + 23
    s24 = s24 + 24
    s25 = s25 + 25
  end do
  bad = 0
  first = -1
  if (s1 /= 105) then
    bad = bad + 1
    if (first < 0) first = 1
  end if
  if (s2 /= 110) then
    bad = bad + 1
    if (first < 0) first = 2
  end if
  if (s3 /= 115) then
    bad = bad + 1
    if (first < 0) first = 3
  end if
  if (s4 /= 120) then
    bad = bad + 1
    if (first < 0) first = 4
  end if
  if (s5 /= 125) then
    bad = bad + 1
    if (first < 0) first = 5
  end if
  if (s6 /= 130) then
    bad = bad + 1
    if (first < 0) first = 6
  end if
  if (s7 /= 135) then
    bad = bad + 1
    if (first < 0) first = 7
  end if
  if (s8 /= 140) then
    bad = bad + 1
    if (first < 0) first = 8
  end if
  if (s9 /= 145) then
    bad = bad + 1
    if (first < 0) first = 9
  end if
  if (s10 /= 150) then
    bad = bad + 1
    if (first < 0) first = 10
  end if
  if (s11 /= 155) then
    bad = bad + 1
    if (first < 0) first = 11
  end if
  if (s12 /= 160) then
    bad = bad + 1
    if (first < 0) first = 12
  end if
  if (s13 /= 165) then
    bad = bad + 1
    if (first < 0) first = 13
  end if
  if (s14 /= 170) then
    bad = bad + 1
    if (first < 0) first = 14
  end if
  if (s15 /= 175) then
    bad = bad + 1
    if (first < 0) first = 15
  end if
  if (s16 /= 180) then
    bad = bad + 1
    if (first < 0) first = 16
  end if
  if (s17 /= 185) then
    bad = bad + 1
    if (first < 0) first = 17
  end if
  if (s18 /= 190) then
    bad = bad + 1
    if (first < 0) first = 18
  end if
  if (s19 /= 195) then
    bad = bad + 1
    if (first < 0) first = 19
  end if
  if (s20 /= 200) then
    bad = bad + 1
    if (first < 0) first = 20
  end if
  if (s21 /= 205) then
    bad = bad + 1
    if (first < 0) first = 21
  end if
  if (s22 /= 210) then
    bad = bad + 1
    if (first < 0) first = 22
  end if
  if (s23 /= 215) then
    bad = bad + 1
    if (first < 0) first = 23
  end if
  if (s24 /= 220) then
    bad = bad + 1
    if (first < 0) first = 24
  end if
  if (s25 /= 225) then
    bad = bad + 1
    if (first < 0) first = 25
  end if
  print '(a,i0,a,i0,a,i0,a,i0)', 'bad= ', bad, ' first= ', first, ' s1= ', s1, ' s25= ', s25
end program p
