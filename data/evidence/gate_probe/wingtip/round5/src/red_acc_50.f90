! 50 integer sum reductions on one OpenACC parallel
! loop (the kernel of the stress program scalars.reduction-acc-200, alone).
! Each s_k starts at 100 + k and adds k in each of 4 iterations, so it ends
! at 100 + 5k (OpenACC 3.4 §2.9.11; §2.11 p.76 l.2790-2791: a reduction
! clause on a combined construct implies a copy clause). Expected: bad= 0
program p
  implicit none
  integer :: ii, bad, first
  integer :: s1, s2, s3, s4, s5, s6, s7, s8, s9, s10
  integer :: s11, s12, s13, s14, s15, s16, s17, s18, s19, s20
  integer :: s21, s22, s23, s24, s25, s26, s27, s28, s29, s30
  integer :: s31, s32, s33, s34, s35, s36, s37, s38, s39, s40
  integer :: s41, s42, s43, s44, s45, s46, s47, s48, s49, s50
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
  s26 = 126
  s27 = 127
  s28 = 128
  s29 = 129
  s30 = 130
  s31 = 131
  s32 = 132
  s33 = 133
  s34 = 134
  s35 = 135
  s36 = 136
  s37 = 137
  s38 = 138
  s39 = 139
  s40 = 140
  s41 = 141
  s42 = 142
  s43 = 143
  s44 = 144
  s45 = 145
  s46 = 146
  s47 = 147
  s48 = 148
  s49 = 149
  s50 = 150
  !$acc parallel loop reduction(+: s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, &
  !$acc& s11, s12, s13, s14, s15, s16, s17, s18, s19, s20, &
  !$acc& s21, s22, s23, s24, s25, s26, s27, s28, s29, s30, &
  !$acc& s31, s32, s33, s34, s35, s36, s37, s38, s39, s40, &
  !$acc& s41, s42, s43, s44, s45, s46, s47, s48, s49, s50)
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
    s26 = s26 + 26
    s27 = s27 + 27
    s28 = s28 + 28
    s29 = s29 + 29
    s30 = s30 + 30
    s31 = s31 + 31
    s32 = s32 + 32
    s33 = s33 + 33
    s34 = s34 + 34
    s35 = s35 + 35
    s36 = s36 + 36
    s37 = s37 + 37
    s38 = s38 + 38
    s39 = s39 + 39
    s40 = s40 + 40
    s41 = s41 + 41
    s42 = s42 + 42
    s43 = s43 + 43
    s44 = s44 + 44
    s45 = s45 + 45
    s46 = s46 + 46
    s47 = s47 + 47
    s48 = s48 + 48
    s49 = s49 + 49
    s50 = s50 + 50
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
  if (s26 /= 230) then
    bad = bad + 1
    if (first < 0) first = 26
  end if
  if (s27 /= 235) then
    bad = bad + 1
    if (first < 0) first = 27
  end if
  if (s28 /= 240) then
    bad = bad + 1
    if (first < 0) first = 28
  end if
  if (s29 /= 245) then
    bad = bad + 1
    if (first < 0) first = 29
  end if
  if (s30 /= 250) then
    bad = bad + 1
    if (first < 0) first = 30
  end if
  if (s31 /= 255) then
    bad = bad + 1
    if (first < 0) first = 31
  end if
  if (s32 /= 260) then
    bad = bad + 1
    if (first < 0) first = 32
  end if
  if (s33 /= 265) then
    bad = bad + 1
    if (first < 0) first = 33
  end if
  if (s34 /= 270) then
    bad = bad + 1
    if (first < 0) first = 34
  end if
  if (s35 /= 275) then
    bad = bad + 1
    if (first < 0) first = 35
  end if
  if (s36 /= 280) then
    bad = bad + 1
    if (first < 0) first = 36
  end if
  if (s37 /= 285) then
    bad = bad + 1
    if (first < 0) first = 37
  end if
  if (s38 /= 290) then
    bad = bad + 1
    if (first < 0) first = 38
  end if
  if (s39 /= 295) then
    bad = bad + 1
    if (first < 0) first = 39
  end if
  if (s40 /= 300) then
    bad = bad + 1
    if (first < 0) first = 40
  end if
  if (s41 /= 305) then
    bad = bad + 1
    if (first < 0) first = 41
  end if
  if (s42 /= 310) then
    bad = bad + 1
    if (first < 0) first = 42
  end if
  if (s43 /= 315) then
    bad = bad + 1
    if (first < 0) first = 43
  end if
  if (s44 /= 320) then
    bad = bad + 1
    if (first < 0) first = 44
  end if
  if (s45 /= 325) then
    bad = bad + 1
    if (first < 0) first = 45
  end if
  if (s46 /= 330) then
    bad = bad + 1
    if (first < 0) first = 46
  end if
  if (s47 /= 335) then
    bad = bad + 1
    if (first < 0) first = 47
  end if
  if (s48 /= 340) then
    bad = bad + 1
    if (first < 0) first = 48
  end if
  if (s49 /= 345) then
    bad = bad + 1
    if (first < 0) first = 49
  end if
  if (s50 /= 350) then
    bad = bad + 1
    if (first < 0) first = 50
  end if
  print '(a,i0,a,i0,a,i0,a,i0)', 'bad= ', bad, ' first= ', first, ' s1= ', s1, ' s50= ', s50
end program p
