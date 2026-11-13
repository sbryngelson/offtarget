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
  if (s1 != 105) { bad++; if (first < 0) first = 1; }
  if (s2 != 110) { bad++; if (first < 0) first = 2; }
  if (s3 != 115) { bad++; if (first < 0) first = 3; }
  if (s4 != 120) { bad++; if (first < 0) first = 4; }
  if (s5 != 125) { bad++; if (first < 0) first = 5; }
  if (s6 != 130) { bad++; if (first < 0) first = 6; }
  if (s7 != 135) { bad++; if (first < 0) first = 7; }
  if (s8 != 140) { bad++; if (first < 0) first = 8; }
  if (s9 != 145) { bad++; if (first < 0) first = 9; }
  if (s10 != 150) { bad++; if (first < 0) first = 10; }
  if (s11 != 155) { bad++; if (first < 0) first = 11; }
  if (s12 != 160) { bad++; if (first < 0) first = 12; }
  if (s13 != 165) { bad++; if (first < 0) first = 13; }
  if (s14 != 170) { bad++; if (first < 0) first = 14; }
  if (s15 != 175) { bad++; if (first < 0) first = 15; }
  if (s16 != 180) { bad++; if (first < 0) first = 16; }
  if (s17 != 185) { bad++; if (first < 0) first = 17; }
  if (s18 != 190) { bad++; if (first < 0) first = 18; }
  if (s19 != 195) { bad++; if (first < 0) first = 19; }
  if (s20 != 200) { bad++; if (first < 0) first = 20; }
  if (s21 != 205) { bad++; if (first < 0) first = 21; }
  if (s22 != 210) { bad++; if (first < 0) first = 22; }
  if (s23 != 215) { bad++; if (first < 0) first = 23; }
  if (s24 != 220) { bad++; if (first < 0) first = 24; }
  if (s25 != 225) { bad++; if (first < 0) first = 25; }
  if (s26 != 230) { bad++; if (first < 0) first = 26; }
  if (s27 != 235) { bad++; if (first < 0) first = 27; }
  if (s28 != 240) { bad++; if (first < 0) first = 28; }
  if (s29 != 245) { bad++; if (first < 0) first = 29; }
  if (s30 != 250) { bad++; if (first < 0) first = 30; }
  if (s31 != 255) { bad++; if (first < 0) first = 31; }
  if (s32 != 260) { bad++; if (first < 0) first = 32; }
  if (s33 != 265) { bad++; if (first < 0) first = 33; }
  if (s34 != 270) { bad++; if (first < 0) first = 34; }
  if (s35 != 275) { bad++; if (first < 0) first = 35; }
  if (s36 != 280) { bad++; if (first < 0) first = 36; }
  if (s37 != 285) { bad++; if (first < 0) first = 37; }
  if (s38 != 290) { bad++; if (first < 0) first = 38; }
  if (s39 != 295) { bad++; if (first < 0) first = 39; }
  if (s40 != 300) { bad++; if (first < 0) first = 40; }
  if (s41 != 305) { bad++; if (first < 0) first = 41; }
  if (s42 != 310) { bad++; if (first < 0) first = 42; }
  if (s43 != 315) { bad++; if (first < 0) first = 43; }
  if (s44 != 320) { bad++; if (first < 0) first = 44; }
  if (s45 != 325) { bad++; if (first < 0) first = 45; }
  if (s46 != 330) { bad++; if (first < 0) first = 46; }
  if (s47 != 335) { bad++; if (first < 0) first = 47; }
  if (s48 != 340) { bad++; if (first < 0) first = 48; }
  if (s49 != 345) { bad++; if (first < 0) first = 49; }
  if (s50 != 350) { bad++; if (first < 0) first = 50; }
  if (s51 != 355) { bad++; if (first < 0) first = 51; }
  if (s52 != 360) { bad++; if (first < 0) first = 52; }
  if (s53 != 365) { bad++; if (first < 0) first = 53; }
  if (s54 != 370) { bad++; if (first < 0) first = 54; }
  if (s55 != 375) { bad++; if (first < 0) first = 55; }
  if (s56 != 380) { bad++; if (first < 0) first = 56; }
  if (s57 != 385) { bad++; if (first < 0) first = 57; }
  if (s58 != 390) { bad++; if (first < 0) first = 58; }
  if (s59 != 395) { bad++; if (first < 0) first = 59; }
  if (s60 != 400) { bad++; if (first < 0) first = 60; }
  if (s61 != 405) { bad++; if (first < 0) first = 61; }
  if (s62 != 410) { bad++; if (first < 0) first = 62; }
  if (s63 != 415) { bad++; if (first < 0) first = 63; }
  if (s64 != 420) { bad++; if (first < 0) first = 64; }
  printf("bad= %d first= %d s1= %ld s64= %ld\n", bad, first, (long) s1, (long) s64);
  return 0;
}
