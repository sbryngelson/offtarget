! (integer(8) scalars) 200 integer sum reductions on one OpenACC parallel
! loop (the kernel of the stress program scalars.reduction-acc-200, alone).
! Each s_k starts at 100 + k and adds k in each of 4 iterations, so it ends
! at 100 + 5k (OpenACC 3.4 §2.9.11; §2.11 p.76 l.2790-2791: a reduction
! clause on a combined construct implies a copy clause). Expected: bad= 0
program p
  implicit none
  integer :: ii, bad, first
  integer(8) :: s1, s2, s3, s4, s5, s6, s7, s8, s9, s10
  integer(8) :: s11, s12, s13, s14, s15, s16, s17, s18, s19, s20
  integer(8) :: s21, s22, s23, s24, s25, s26, s27, s28, s29, s30
  integer(8) :: s31, s32, s33, s34, s35, s36, s37, s38, s39, s40
  integer(8) :: s41, s42, s43, s44, s45, s46, s47, s48, s49, s50
  integer(8) :: s51, s52, s53, s54, s55, s56, s57, s58, s59, s60
  integer(8) :: s61, s62, s63, s64, s65, s66, s67, s68, s69, s70
  integer(8) :: s71, s72, s73, s74, s75, s76, s77, s78, s79, s80
  integer(8) :: s81, s82, s83, s84, s85, s86, s87, s88, s89, s90
  integer(8) :: s91, s92, s93, s94, s95, s96, s97, s98, s99, s100
  integer(8) :: s101, s102, s103, s104, s105, s106, s107, s108, s109, s110
  integer(8) :: s111, s112, s113, s114, s115, s116, s117, s118, s119, s120
  integer(8) :: s121, s122, s123, s124, s125, s126, s127, s128, s129, s130
  integer(8) :: s131, s132, s133, s134, s135, s136, s137, s138, s139, s140
  integer(8) :: s141, s142, s143, s144, s145, s146, s147, s148, s149, s150
  integer(8) :: s151, s152, s153, s154, s155, s156, s157, s158, s159, s160
  integer(8) :: s161, s162, s163, s164, s165, s166, s167, s168, s169, s170
  integer(8) :: s171, s172, s173, s174, s175, s176, s177, s178, s179, s180
  integer(8) :: s181, s182, s183, s184, s185, s186, s187, s188, s189, s190
  integer(8) :: s191, s192, s193, s194, s195, s196, s197, s198, s199, s200
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
  s51 = 151
  s52 = 152
  s53 = 153
  s54 = 154
  s55 = 155
  s56 = 156
  s57 = 157
  s58 = 158
  s59 = 159
  s60 = 160
  s61 = 161
  s62 = 162
  s63 = 163
  s64 = 164
  s65 = 165
  s66 = 166
  s67 = 167
  s68 = 168
  s69 = 169
  s70 = 170
  s71 = 171
  s72 = 172
  s73 = 173
  s74 = 174
  s75 = 175
  s76 = 176
  s77 = 177
  s78 = 178
  s79 = 179
  s80 = 180
  s81 = 181
  s82 = 182
  s83 = 183
  s84 = 184
  s85 = 185
  s86 = 186
  s87 = 187
  s88 = 188
  s89 = 189
  s90 = 190
  s91 = 191
  s92 = 192
  s93 = 193
  s94 = 194
  s95 = 195
  s96 = 196
  s97 = 197
  s98 = 198
  s99 = 199
  s100 = 200
  s101 = 201
  s102 = 202
  s103 = 203
  s104 = 204
  s105 = 205
  s106 = 206
  s107 = 207
  s108 = 208
  s109 = 209
  s110 = 210
  s111 = 211
  s112 = 212
  s113 = 213
  s114 = 214
  s115 = 215
  s116 = 216
  s117 = 217
  s118 = 218
  s119 = 219
  s120 = 220
  s121 = 221
  s122 = 222
  s123 = 223
  s124 = 224
  s125 = 225
  s126 = 226
  s127 = 227
  s128 = 228
  s129 = 229
  s130 = 230
  s131 = 231
  s132 = 232
  s133 = 233
  s134 = 234
  s135 = 235
  s136 = 236
  s137 = 237
  s138 = 238
  s139 = 239
  s140 = 240
  s141 = 241
  s142 = 242
  s143 = 243
  s144 = 244
  s145 = 245
  s146 = 246
  s147 = 247
  s148 = 248
  s149 = 249
  s150 = 250
  s151 = 251
  s152 = 252
  s153 = 253
  s154 = 254
  s155 = 255
  s156 = 256
  s157 = 257
  s158 = 258
  s159 = 259
  s160 = 260
  s161 = 261
  s162 = 262
  s163 = 263
  s164 = 264
  s165 = 265
  s166 = 266
  s167 = 267
  s168 = 268
  s169 = 269
  s170 = 270
  s171 = 271
  s172 = 272
  s173 = 273
  s174 = 274
  s175 = 275
  s176 = 276
  s177 = 277
  s178 = 278
  s179 = 279
  s180 = 280
  s181 = 281
  s182 = 282
  s183 = 283
  s184 = 284
  s185 = 285
  s186 = 286
  s187 = 287
  s188 = 288
  s189 = 289
  s190 = 290
  s191 = 291
  s192 = 292
  s193 = 293
  s194 = 294
  s195 = 295
  s196 = 296
  s197 = 297
  s198 = 298
  s199 = 299
  s200 = 300
  !$acc parallel loop reduction(+: s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, &
  !$acc& s11, s12, s13, s14, s15, s16, s17, s18, s19, s20, &
  !$acc& s21, s22, s23, s24, s25, s26, s27, s28, s29, s30, &
  !$acc& s31, s32, s33, s34, s35, s36, s37, s38, s39, s40, &
  !$acc& s41, s42, s43, s44, s45, s46, s47, s48, s49, s50, &
  !$acc& s51, s52, s53, s54, s55, s56, s57, s58, s59, s60, &
  !$acc& s61, s62, s63, s64, s65, s66, s67, s68, s69, s70, &
  !$acc& s71, s72, s73, s74, s75, s76, s77, s78, s79, s80, &
  !$acc& s81, s82, s83, s84, s85, s86, s87, s88, s89, s90, &
  !$acc& s91, s92, s93, s94, s95, s96, s97, s98, s99, s100, &
  !$acc& s101, s102, s103, s104, s105, s106, s107, s108, s109, s110, &
  !$acc& s111, s112, s113, s114, s115, s116, s117, s118, s119, s120, &
  !$acc& s121, s122, s123, s124, s125, s126, s127, s128, s129, s130, &
  !$acc& s131, s132, s133, s134, s135, s136, s137, s138, s139, s140, &
  !$acc& s141, s142, s143, s144, s145, s146, s147, s148, s149, s150, &
  !$acc& s151, s152, s153, s154, s155, s156, s157, s158, s159, s160, &
  !$acc& s161, s162, s163, s164, s165, s166, s167, s168, s169, s170, &
  !$acc& s171, s172, s173, s174, s175, s176, s177, s178, s179, s180, &
  !$acc& s181, s182, s183, s184, s185, s186, s187, s188, s189, s190, &
  !$acc& s191, s192, s193, s194, s195, s196, s197, s198, s199, s200)
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
    s51 = s51 + 51
    s52 = s52 + 52
    s53 = s53 + 53
    s54 = s54 + 54
    s55 = s55 + 55
    s56 = s56 + 56
    s57 = s57 + 57
    s58 = s58 + 58
    s59 = s59 + 59
    s60 = s60 + 60
    s61 = s61 + 61
    s62 = s62 + 62
    s63 = s63 + 63
    s64 = s64 + 64
    s65 = s65 + 65
    s66 = s66 + 66
    s67 = s67 + 67
    s68 = s68 + 68
    s69 = s69 + 69
    s70 = s70 + 70
    s71 = s71 + 71
    s72 = s72 + 72
    s73 = s73 + 73
    s74 = s74 + 74
    s75 = s75 + 75
    s76 = s76 + 76
    s77 = s77 + 77
    s78 = s78 + 78
    s79 = s79 + 79
    s80 = s80 + 80
    s81 = s81 + 81
    s82 = s82 + 82
    s83 = s83 + 83
    s84 = s84 + 84
    s85 = s85 + 85
    s86 = s86 + 86
    s87 = s87 + 87
    s88 = s88 + 88
    s89 = s89 + 89
    s90 = s90 + 90
    s91 = s91 + 91
    s92 = s92 + 92
    s93 = s93 + 93
    s94 = s94 + 94
    s95 = s95 + 95
    s96 = s96 + 96
    s97 = s97 + 97
    s98 = s98 + 98
    s99 = s99 + 99
    s100 = s100 + 100
    s101 = s101 + 101
    s102 = s102 + 102
    s103 = s103 + 103
    s104 = s104 + 104
    s105 = s105 + 105
    s106 = s106 + 106
    s107 = s107 + 107
    s108 = s108 + 108
    s109 = s109 + 109
    s110 = s110 + 110
    s111 = s111 + 111
    s112 = s112 + 112
    s113 = s113 + 113
    s114 = s114 + 114
    s115 = s115 + 115
    s116 = s116 + 116
    s117 = s117 + 117
    s118 = s118 + 118
    s119 = s119 + 119
    s120 = s120 + 120
    s121 = s121 + 121
    s122 = s122 + 122
    s123 = s123 + 123
    s124 = s124 + 124
    s125 = s125 + 125
    s126 = s126 + 126
    s127 = s127 + 127
    s128 = s128 + 128
    s129 = s129 + 129
    s130 = s130 + 130
    s131 = s131 + 131
    s132 = s132 + 132
    s133 = s133 + 133
    s134 = s134 + 134
    s135 = s135 + 135
    s136 = s136 + 136
    s137 = s137 + 137
    s138 = s138 + 138
    s139 = s139 + 139
    s140 = s140 + 140
    s141 = s141 + 141
    s142 = s142 + 142
    s143 = s143 + 143
    s144 = s144 + 144
    s145 = s145 + 145
    s146 = s146 + 146
    s147 = s147 + 147
    s148 = s148 + 148
    s149 = s149 + 149
    s150 = s150 + 150
    s151 = s151 + 151
    s152 = s152 + 152
    s153 = s153 + 153
    s154 = s154 + 154
    s155 = s155 + 155
    s156 = s156 + 156
    s157 = s157 + 157
    s158 = s158 + 158
    s159 = s159 + 159
    s160 = s160 + 160
    s161 = s161 + 161
    s162 = s162 + 162
    s163 = s163 + 163
    s164 = s164 + 164
    s165 = s165 + 165
    s166 = s166 + 166
    s167 = s167 + 167
    s168 = s168 + 168
    s169 = s169 + 169
    s170 = s170 + 170
    s171 = s171 + 171
    s172 = s172 + 172
    s173 = s173 + 173
    s174 = s174 + 174
    s175 = s175 + 175
    s176 = s176 + 176
    s177 = s177 + 177
    s178 = s178 + 178
    s179 = s179 + 179
    s180 = s180 + 180
    s181 = s181 + 181
    s182 = s182 + 182
    s183 = s183 + 183
    s184 = s184 + 184
    s185 = s185 + 185
    s186 = s186 + 186
    s187 = s187 + 187
    s188 = s188 + 188
    s189 = s189 + 189
    s190 = s190 + 190
    s191 = s191 + 191
    s192 = s192 + 192
    s193 = s193 + 193
    s194 = s194 + 194
    s195 = s195 + 195
    s196 = s196 + 196
    s197 = s197 + 197
    s198 = s198 + 198
    s199 = s199 + 199
    s200 = s200 + 200
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
  if (s51 /= 355) then
    bad = bad + 1
    if (first < 0) first = 51
  end if
  if (s52 /= 360) then
    bad = bad + 1
    if (first < 0) first = 52
  end if
  if (s53 /= 365) then
    bad = bad + 1
    if (first < 0) first = 53
  end if
  if (s54 /= 370) then
    bad = bad + 1
    if (first < 0) first = 54
  end if
  if (s55 /= 375) then
    bad = bad + 1
    if (first < 0) first = 55
  end if
  if (s56 /= 380) then
    bad = bad + 1
    if (first < 0) first = 56
  end if
  if (s57 /= 385) then
    bad = bad + 1
    if (first < 0) first = 57
  end if
  if (s58 /= 390) then
    bad = bad + 1
    if (first < 0) first = 58
  end if
  if (s59 /= 395) then
    bad = bad + 1
    if (first < 0) first = 59
  end if
  if (s60 /= 400) then
    bad = bad + 1
    if (first < 0) first = 60
  end if
  if (s61 /= 405) then
    bad = bad + 1
    if (first < 0) first = 61
  end if
  if (s62 /= 410) then
    bad = bad + 1
    if (first < 0) first = 62
  end if
  if (s63 /= 415) then
    bad = bad + 1
    if (first < 0) first = 63
  end if
  if (s64 /= 420) then
    bad = bad + 1
    if (first < 0) first = 64
  end if
  if (s65 /= 425) then
    bad = bad + 1
    if (first < 0) first = 65
  end if
  if (s66 /= 430) then
    bad = bad + 1
    if (first < 0) first = 66
  end if
  if (s67 /= 435) then
    bad = bad + 1
    if (first < 0) first = 67
  end if
  if (s68 /= 440) then
    bad = bad + 1
    if (first < 0) first = 68
  end if
  if (s69 /= 445) then
    bad = bad + 1
    if (first < 0) first = 69
  end if
  if (s70 /= 450) then
    bad = bad + 1
    if (first < 0) first = 70
  end if
  if (s71 /= 455) then
    bad = bad + 1
    if (first < 0) first = 71
  end if
  if (s72 /= 460) then
    bad = bad + 1
    if (first < 0) first = 72
  end if
  if (s73 /= 465) then
    bad = bad + 1
    if (first < 0) first = 73
  end if
  if (s74 /= 470) then
    bad = bad + 1
    if (first < 0) first = 74
  end if
  if (s75 /= 475) then
    bad = bad + 1
    if (first < 0) first = 75
  end if
  if (s76 /= 480) then
    bad = bad + 1
    if (first < 0) first = 76
  end if
  if (s77 /= 485) then
    bad = bad + 1
    if (first < 0) first = 77
  end if
  if (s78 /= 490) then
    bad = bad + 1
    if (first < 0) first = 78
  end if
  if (s79 /= 495) then
    bad = bad + 1
    if (first < 0) first = 79
  end if
  if (s80 /= 500) then
    bad = bad + 1
    if (first < 0) first = 80
  end if
  if (s81 /= 505) then
    bad = bad + 1
    if (first < 0) first = 81
  end if
  if (s82 /= 510) then
    bad = bad + 1
    if (first < 0) first = 82
  end if
  if (s83 /= 515) then
    bad = bad + 1
    if (first < 0) first = 83
  end if
  if (s84 /= 520) then
    bad = bad + 1
    if (first < 0) first = 84
  end if
  if (s85 /= 525) then
    bad = bad + 1
    if (first < 0) first = 85
  end if
  if (s86 /= 530) then
    bad = bad + 1
    if (first < 0) first = 86
  end if
  if (s87 /= 535) then
    bad = bad + 1
    if (first < 0) first = 87
  end if
  if (s88 /= 540) then
    bad = bad + 1
    if (first < 0) first = 88
  end if
  if (s89 /= 545) then
    bad = bad + 1
    if (first < 0) first = 89
  end if
  if (s90 /= 550) then
    bad = bad + 1
    if (first < 0) first = 90
  end if
  if (s91 /= 555) then
    bad = bad + 1
    if (first < 0) first = 91
  end if
  if (s92 /= 560) then
    bad = bad + 1
    if (first < 0) first = 92
  end if
  if (s93 /= 565) then
    bad = bad + 1
    if (first < 0) first = 93
  end if
  if (s94 /= 570) then
    bad = bad + 1
    if (first < 0) first = 94
  end if
  if (s95 /= 575) then
    bad = bad + 1
    if (first < 0) first = 95
  end if
  if (s96 /= 580) then
    bad = bad + 1
    if (first < 0) first = 96
  end if
  if (s97 /= 585) then
    bad = bad + 1
    if (first < 0) first = 97
  end if
  if (s98 /= 590) then
    bad = bad + 1
    if (first < 0) first = 98
  end if
  if (s99 /= 595) then
    bad = bad + 1
    if (first < 0) first = 99
  end if
  if (s100 /= 600) then
    bad = bad + 1
    if (first < 0) first = 100
  end if
  if (s101 /= 605) then
    bad = bad + 1
    if (first < 0) first = 101
  end if
  if (s102 /= 610) then
    bad = bad + 1
    if (first < 0) first = 102
  end if
  if (s103 /= 615) then
    bad = bad + 1
    if (first < 0) first = 103
  end if
  if (s104 /= 620) then
    bad = bad + 1
    if (first < 0) first = 104
  end if
  if (s105 /= 625) then
    bad = bad + 1
    if (first < 0) first = 105
  end if
  if (s106 /= 630) then
    bad = bad + 1
    if (first < 0) first = 106
  end if
  if (s107 /= 635) then
    bad = bad + 1
    if (first < 0) first = 107
  end if
  if (s108 /= 640) then
    bad = bad + 1
    if (first < 0) first = 108
  end if
  if (s109 /= 645) then
    bad = bad + 1
    if (first < 0) first = 109
  end if
  if (s110 /= 650) then
    bad = bad + 1
    if (first < 0) first = 110
  end if
  if (s111 /= 655) then
    bad = bad + 1
    if (first < 0) first = 111
  end if
  if (s112 /= 660) then
    bad = bad + 1
    if (first < 0) first = 112
  end if
  if (s113 /= 665) then
    bad = bad + 1
    if (first < 0) first = 113
  end if
  if (s114 /= 670) then
    bad = bad + 1
    if (first < 0) first = 114
  end if
  if (s115 /= 675) then
    bad = bad + 1
    if (first < 0) first = 115
  end if
  if (s116 /= 680) then
    bad = bad + 1
    if (first < 0) first = 116
  end if
  if (s117 /= 685) then
    bad = bad + 1
    if (first < 0) first = 117
  end if
  if (s118 /= 690) then
    bad = bad + 1
    if (first < 0) first = 118
  end if
  if (s119 /= 695) then
    bad = bad + 1
    if (first < 0) first = 119
  end if
  if (s120 /= 700) then
    bad = bad + 1
    if (first < 0) first = 120
  end if
  if (s121 /= 705) then
    bad = bad + 1
    if (first < 0) first = 121
  end if
  if (s122 /= 710) then
    bad = bad + 1
    if (first < 0) first = 122
  end if
  if (s123 /= 715) then
    bad = bad + 1
    if (first < 0) first = 123
  end if
  if (s124 /= 720) then
    bad = bad + 1
    if (first < 0) first = 124
  end if
  if (s125 /= 725) then
    bad = bad + 1
    if (first < 0) first = 125
  end if
  if (s126 /= 730) then
    bad = bad + 1
    if (first < 0) first = 126
  end if
  if (s127 /= 735) then
    bad = bad + 1
    if (first < 0) first = 127
  end if
  if (s128 /= 740) then
    bad = bad + 1
    if (first < 0) first = 128
  end if
  if (s129 /= 745) then
    bad = bad + 1
    if (first < 0) first = 129
  end if
  if (s130 /= 750) then
    bad = bad + 1
    if (first < 0) first = 130
  end if
  if (s131 /= 755) then
    bad = bad + 1
    if (first < 0) first = 131
  end if
  if (s132 /= 760) then
    bad = bad + 1
    if (first < 0) first = 132
  end if
  if (s133 /= 765) then
    bad = bad + 1
    if (first < 0) first = 133
  end if
  if (s134 /= 770) then
    bad = bad + 1
    if (first < 0) first = 134
  end if
  if (s135 /= 775) then
    bad = bad + 1
    if (first < 0) first = 135
  end if
  if (s136 /= 780) then
    bad = bad + 1
    if (first < 0) first = 136
  end if
  if (s137 /= 785) then
    bad = bad + 1
    if (first < 0) first = 137
  end if
  if (s138 /= 790) then
    bad = bad + 1
    if (first < 0) first = 138
  end if
  if (s139 /= 795) then
    bad = bad + 1
    if (first < 0) first = 139
  end if
  if (s140 /= 800) then
    bad = bad + 1
    if (first < 0) first = 140
  end if
  if (s141 /= 805) then
    bad = bad + 1
    if (first < 0) first = 141
  end if
  if (s142 /= 810) then
    bad = bad + 1
    if (first < 0) first = 142
  end if
  if (s143 /= 815) then
    bad = bad + 1
    if (first < 0) first = 143
  end if
  if (s144 /= 820) then
    bad = bad + 1
    if (first < 0) first = 144
  end if
  if (s145 /= 825) then
    bad = bad + 1
    if (first < 0) first = 145
  end if
  if (s146 /= 830) then
    bad = bad + 1
    if (first < 0) first = 146
  end if
  if (s147 /= 835) then
    bad = bad + 1
    if (first < 0) first = 147
  end if
  if (s148 /= 840) then
    bad = bad + 1
    if (first < 0) first = 148
  end if
  if (s149 /= 845) then
    bad = bad + 1
    if (first < 0) first = 149
  end if
  if (s150 /= 850) then
    bad = bad + 1
    if (first < 0) first = 150
  end if
  if (s151 /= 855) then
    bad = bad + 1
    if (first < 0) first = 151
  end if
  if (s152 /= 860) then
    bad = bad + 1
    if (first < 0) first = 152
  end if
  if (s153 /= 865) then
    bad = bad + 1
    if (first < 0) first = 153
  end if
  if (s154 /= 870) then
    bad = bad + 1
    if (first < 0) first = 154
  end if
  if (s155 /= 875) then
    bad = bad + 1
    if (first < 0) first = 155
  end if
  if (s156 /= 880) then
    bad = bad + 1
    if (first < 0) first = 156
  end if
  if (s157 /= 885) then
    bad = bad + 1
    if (first < 0) first = 157
  end if
  if (s158 /= 890) then
    bad = bad + 1
    if (first < 0) first = 158
  end if
  if (s159 /= 895) then
    bad = bad + 1
    if (first < 0) first = 159
  end if
  if (s160 /= 900) then
    bad = bad + 1
    if (first < 0) first = 160
  end if
  if (s161 /= 905) then
    bad = bad + 1
    if (first < 0) first = 161
  end if
  if (s162 /= 910) then
    bad = bad + 1
    if (first < 0) first = 162
  end if
  if (s163 /= 915) then
    bad = bad + 1
    if (first < 0) first = 163
  end if
  if (s164 /= 920) then
    bad = bad + 1
    if (first < 0) first = 164
  end if
  if (s165 /= 925) then
    bad = bad + 1
    if (first < 0) first = 165
  end if
  if (s166 /= 930) then
    bad = bad + 1
    if (first < 0) first = 166
  end if
  if (s167 /= 935) then
    bad = bad + 1
    if (first < 0) first = 167
  end if
  if (s168 /= 940) then
    bad = bad + 1
    if (first < 0) first = 168
  end if
  if (s169 /= 945) then
    bad = bad + 1
    if (first < 0) first = 169
  end if
  if (s170 /= 950) then
    bad = bad + 1
    if (first < 0) first = 170
  end if
  if (s171 /= 955) then
    bad = bad + 1
    if (first < 0) first = 171
  end if
  if (s172 /= 960) then
    bad = bad + 1
    if (first < 0) first = 172
  end if
  if (s173 /= 965) then
    bad = bad + 1
    if (first < 0) first = 173
  end if
  if (s174 /= 970) then
    bad = bad + 1
    if (first < 0) first = 174
  end if
  if (s175 /= 975) then
    bad = bad + 1
    if (first < 0) first = 175
  end if
  if (s176 /= 980) then
    bad = bad + 1
    if (first < 0) first = 176
  end if
  if (s177 /= 985) then
    bad = bad + 1
    if (first < 0) first = 177
  end if
  if (s178 /= 990) then
    bad = bad + 1
    if (first < 0) first = 178
  end if
  if (s179 /= 995) then
    bad = bad + 1
    if (first < 0) first = 179
  end if
  if (s180 /= 1000) then
    bad = bad + 1
    if (first < 0) first = 180
  end if
  if (s181 /= 1005) then
    bad = bad + 1
    if (first < 0) first = 181
  end if
  if (s182 /= 1010) then
    bad = bad + 1
    if (first < 0) first = 182
  end if
  if (s183 /= 1015) then
    bad = bad + 1
    if (first < 0) first = 183
  end if
  if (s184 /= 1020) then
    bad = bad + 1
    if (first < 0) first = 184
  end if
  if (s185 /= 1025) then
    bad = bad + 1
    if (first < 0) first = 185
  end if
  if (s186 /= 1030) then
    bad = bad + 1
    if (first < 0) first = 186
  end if
  if (s187 /= 1035) then
    bad = bad + 1
    if (first < 0) first = 187
  end if
  if (s188 /= 1040) then
    bad = bad + 1
    if (first < 0) first = 188
  end if
  if (s189 /= 1045) then
    bad = bad + 1
    if (first < 0) first = 189
  end if
  if (s190 /= 1050) then
    bad = bad + 1
    if (first < 0) first = 190
  end if
  if (s191 /= 1055) then
    bad = bad + 1
    if (first < 0) first = 191
  end if
  if (s192 /= 1060) then
    bad = bad + 1
    if (first < 0) first = 192
  end if
  if (s193 /= 1065) then
    bad = bad + 1
    if (first < 0) first = 193
  end if
  if (s194 /= 1070) then
    bad = bad + 1
    if (first < 0) first = 194
  end if
  if (s195 /= 1075) then
    bad = bad + 1
    if (first < 0) first = 195
  end if
  if (s196 /= 1080) then
    bad = bad + 1
    if (first < 0) first = 196
  end if
  if (s197 /= 1085) then
    bad = bad + 1
    if (first < 0) first = 197
  end if
  if (s198 /= 1090) then
    bad = bad + 1
    if (first < 0) first = 198
  end if
  if (s199 /= 1095) then
    bad = bad + 1
    if (first < 0) first = 199
  end if
  if (s200 /= 1100) then
    bad = bad + 1
    if (first < 0) first = 200
  end if
  print '(a,i0,a,i0,a,i0,a,i0)', 'bad= ', bad, ' first= ', first, ' s1= ', s1, ' s200= ', s200
end program p
