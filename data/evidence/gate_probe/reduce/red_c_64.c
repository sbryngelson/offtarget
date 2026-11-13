// 64 int64 sum reductions on one combined target
// construct (the kernel k0012 of the stress program scalars-c-64, alone).
// Each s_k starts at 100 + k and adds k in each of 4 iterations, so it ends
// at 100 + 5k (OpenMP 5.2 §5.5.8; §17.2 p.340: on a combined target
// construct a reduction list item is also map(tofrom)). Expected: bad= 0
#include <stdio.h>
#include <stdint.h>
int main(void) {
  int64_t s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13, s14, s15, s16, s17, s18, s19, s20, s21, s22, s23, s24, s25, s26, s27, s28, s29, s30, s31, s32, s33, s34, s35, s36, s37, s38, s39, s40, s41, s42, s43, s44, s45, s46, s47, s48, s49, s50, s51, s52, s53, s54, s55, s56, s57, s58, s59, s60, s61, s62, s63, s64;
  s1 = 101;
  s2 = 102;
  s3 = 103;
  s4 = 104;
  s5 = 105;
  s6 = 106;
  s7 = 107;
  s8 = 108;
  s9 = 109;
  s10 = 110;
  s11 = 111;
  s12 = 112;
  s13 = 113;
  s14 = 114;
  s15 = 115;
  s16 = 116;
  s17 = 117;
  s18 = 118;
  s19 = 119;
  s20 = 120;
  s21 = 121;
  s22 = 122;
  s23 = 123;
  s24 = 124;
  s25 = 125;
  s26 = 126;
  s27 = 127;
  s28 = 128;
  s29 = 129;
  s30 = 130;
  s31 = 131;
  s32 = 132;
  s33 = 133;
  s34 = 134;
  s35 = 135;
  s36 = 136;
  s37 = 137;
  s38 = 138;
  s39 = 139;
  s40 = 140;
  s41 = 141;
  s42 = 142;
  s43 = 143;
  s44 = 144;
  s45 = 145;
  s46 = 146;
  s47 = 147;
  s48 = 148;
  s49 = 149;
  s50 = 150;
  s51 = 151;
  s52 = 152;
  s53 = 153;
  s54 = 154;
  s55 = 155;
  s56 = 156;
  s57 = 157;
  s58 = 158;
  s59 = 159;
  s60 = 160;
  s61 = 161;
  s62 = 162;
  s63 = 163;
  s64 = 164;
  #pragma omp target teams distribute parallel for reduction(+: s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13, s14, s15, s16, s17, s18, s19, s20, s21, s22, s23, s24, s25, s26, s27, s28, s29, s30, s31, s32, s33, s34, s35, s36, s37, s38, s39, s40, s41, s42, s43, s44, s45, s46, s47, s48, s49, s50, s51, s52, s53, s54, s55, s56, s57, s58, s59, s60, s61, s62, s63, s64)
  for (int ii = 0; ii < 4; ii++) {
    s1 += 1;
    s2 += 2;
    s3 += 3;
    s4 += 4;
    s5 += 5;
    s6 += 6;
    s7 += 7;
    s8 += 8;
    s9 += 9;
    s10 += 10;
    s11 += 11;
    s12 += 12;
    s13 += 13;
    s14 += 14;
    s15 += 15;
    s16 += 16;
    s17 += 17;
    s18 += 18;
    s19 += 19;
    s20 += 20;
    s21 += 21;
    s22 += 22;
    s23 += 23;
    s24 += 24;
    s25 += 25;
    s26 += 26;
    s27 += 27;
    s28 += 28;
    s29 += 29;
    s30 += 30;
    s31 += 31;
    s32 += 32;
    s33 += 33;
    s34 += 34;
    s35 += 35;
    s36 += 36;
    s37 += 37;
    s38 += 38;
    s39 += 39;
    s40 += 40;
    s41 += 41;
    s42 += 42;
    s43 += 43;
    s44 += 44;
    s45 += 45;
    s46 += 46;
    s47 += 47;
    s48 += 48;
    s49 += 49;
    s50 += 50;
    s51 += 51;
    s52 += 52;
    s53 += 53;
    s54 += 54;
    s55 += 55;
    s56 += 56;
    s57 += 57;
    s58 += 58;
    s59 += 59;
    s60 += 60;
    s61 += 61;
    s62 += 62;
    s63 += 63;
    s64 += 64;
  }
  int bad = 0, first = -1;
  long fv = 0;
  if (s1 != 105) { bad++; if (first < 0) { first = 1; fv = (long) s1; } }
  if (s2 != 110) { bad++; if (first < 0) { first = 2; fv = (long) s2; } }
  if (s3 != 115) { bad++; if (first < 0) { first = 3; fv = (long) s3; } }
  if (s4 != 120) { bad++; if (first < 0) { first = 4; fv = (long) s4; } }
  if (s5 != 125) { bad++; if (first < 0) { first = 5; fv = (long) s5; } }
  if (s6 != 130) { bad++; if (first < 0) { first = 6; fv = (long) s6; } }
  if (s7 != 135) { bad++; if (first < 0) { first = 7; fv = (long) s7; } }
  if (s8 != 140) { bad++; if (first < 0) { first = 8; fv = (long) s8; } }
  if (s9 != 145) { bad++; if (first < 0) { first = 9; fv = (long) s9; } }
  if (s10 != 150) { bad++; if (first < 0) { first = 10; fv = (long) s10; } }
  if (s11 != 155) { bad++; if (first < 0) { first = 11; fv = (long) s11; } }
  if (s12 != 160) { bad++; if (first < 0) { first = 12; fv = (long) s12; } }
  if (s13 != 165) { bad++; if (first < 0) { first = 13; fv = (long) s13; } }
  if (s14 != 170) { bad++; if (first < 0) { first = 14; fv = (long) s14; } }
  if (s15 != 175) { bad++; if (first < 0) { first = 15; fv = (long) s15; } }
  if (s16 != 180) { bad++; if (first < 0) { first = 16; fv = (long) s16; } }
  if (s17 != 185) { bad++; if (first < 0) { first = 17; fv = (long) s17; } }
  if (s18 != 190) { bad++; if (first < 0) { first = 18; fv = (long) s18; } }
  if (s19 != 195) { bad++; if (first < 0) { first = 19; fv = (long) s19; } }
  if (s20 != 200) { bad++; if (first < 0) { first = 20; fv = (long) s20; } }
  if (s21 != 205) { bad++; if (first < 0) { first = 21; fv = (long) s21; } }
  if (s22 != 210) { bad++; if (first < 0) { first = 22; fv = (long) s22; } }
  if (s23 != 215) { bad++; if (first < 0) { first = 23; fv = (long) s23; } }
  if (s24 != 220) { bad++; if (first < 0) { first = 24; fv = (long) s24; } }
  if (s25 != 225) { bad++; if (first < 0) { first = 25; fv = (long) s25; } }
  if (s26 != 230) { bad++; if (first < 0) { first = 26; fv = (long) s26; } }
  if (s27 != 235) { bad++; if (first < 0) { first = 27; fv = (long) s27; } }
  if (s28 != 240) { bad++; if (first < 0) { first = 28; fv = (long) s28; } }
  if (s29 != 245) { bad++; if (first < 0) { first = 29; fv = (long) s29; } }
  if (s30 != 250) { bad++; if (first < 0) { first = 30; fv = (long) s30; } }
  if (s31 != 255) { bad++; if (first < 0) { first = 31; fv = (long) s31; } }
  if (s32 != 260) { bad++; if (first < 0) { first = 32; fv = (long) s32; } }
  if (s33 != 265) { bad++; if (first < 0) { first = 33; fv = (long) s33; } }
  if (s34 != 270) { bad++; if (first < 0) { first = 34; fv = (long) s34; } }
  if (s35 != 275) { bad++; if (first < 0) { first = 35; fv = (long) s35; } }
  if (s36 != 280) { bad++; if (first < 0) { first = 36; fv = (long) s36; } }
  if (s37 != 285) { bad++; if (first < 0) { first = 37; fv = (long) s37; } }
  if (s38 != 290) { bad++; if (first < 0) { first = 38; fv = (long) s38; } }
  if (s39 != 295) { bad++; if (first < 0) { first = 39; fv = (long) s39; } }
  if (s40 != 300) { bad++; if (first < 0) { first = 40; fv = (long) s40; } }
  if (s41 != 305) { bad++; if (first < 0) { first = 41; fv = (long) s41; } }
  if (s42 != 310) { bad++; if (first < 0) { first = 42; fv = (long) s42; } }
  if (s43 != 315) { bad++; if (first < 0) { first = 43; fv = (long) s43; } }
  if (s44 != 320) { bad++; if (first < 0) { first = 44; fv = (long) s44; } }
  if (s45 != 325) { bad++; if (first < 0) { first = 45; fv = (long) s45; } }
  if (s46 != 330) { bad++; if (first < 0) { first = 46; fv = (long) s46; } }
  if (s47 != 335) { bad++; if (first < 0) { first = 47; fv = (long) s47; } }
  if (s48 != 340) { bad++; if (first < 0) { first = 48; fv = (long) s48; } }
  if (s49 != 345) { bad++; if (first < 0) { first = 49; fv = (long) s49; } }
  if (s50 != 350) { bad++; if (first < 0) { first = 50; fv = (long) s50; } }
  if (s51 != 355) { bad++; if (first < 0) { first = 51; fv = (long) s51; } }
  if (s52 != 360) { bad++; if (first < 0) { first = 52; fv = (long) s52; } }
  if (s53 != 365) { bad++; if (first < 0) { first = 53; fv = (long) s53; } }
  if (s54 != 370) { bad++; if (first < 0) { first = 54; fv = (long) s54; } }
  if (s55 != 375) { bad++; if (first < 0) { first = 55; fv = (long) s55; } }
  if (s56 != 380) { bad++; if (first < 0) { first = 56; fv = (long) s56; } }
  if (s57 != 385) { bad++; if (first < 0) { first = 57; fv = (long) s57; } }
  if (s58 != 390) { bad++; if (first < 0) { first = 58; fv = (long) s58; } }
  if (s59 != 395) { bad++; if (first < 0) { first = 59; fv = (long) s59; } }
  if (s60 != 400) { bad++; if (first < 0) { first = 60; fv = (long) s60; } }
  if (s61 != 405) { bad++; if (first < 0) { first = 61; fv = (long) s61; } }
  if (s62 != 410) { bad++; if (first < 0) { first = 62; fv = (long) s62; } }
  if (s63 != 415) { bad++; if (first < 0) { first = 63; fv = (long) s63; } }
  if (s64 != 420) { bad++; if (first < 0) { first = 64; fv = (long) s64; } }
  printf("bad= %d first= %d (value %ld, expected %ld) s1= %ld s64= %ld\n", bad, first, fv,
         first < 0 ? 0L : 100L + 5L * first, (long) s1, (long) s64);
  return 0;
}
