"""The Fortran self-check of a converted Fortran test (offload.engine.harvest.convert),
the counterpart of c_runtime.py. It follows the Fortran rules of
offload.engine.harvest.checks (`match_stream`): output is one token stream
without commas and record boundaries, and a repeated value r*c is r tokens c.

The original main program becomes `subroutine hv_orig_main` with a bare
`save`. A new main program calls hv_begin (one target region setting
ran_on_host; stdout, and stderr when merged, goes to a file through the C
library), the original, then hv_end. A STOP ends the program through exit,
so hv_begin registers hv_atexit with atexit. hv_end uses only the C library
for I/O, after a FLUSH of unit 6.

@@DATA@@, @@SET@@ and @@REQUIRES@@ are replaced by the check parameters, the
pattern assignments and the original's requires directive."""

RUNTIME = r"""
! ===== self-check (offload/engine/harvest/f_runtime.py) =====
module hv_state
  use, intrinsic :: iso_c_binding
  implicit none
@@DATA@@
  integer(c_int), save :: hv_out = -1, hv_err = -1
  integer, save :: hv_host = 1
  logical, save :: hv_done = .false.
  character(len=96), save :: hv_path = ' '
  character(len=:), allocatable, save :: hv_text
  integer, allocatable, save :: hv_ts(:), hv_te(:)
  integer, save :: hv_nt = 0
  integer, save :: hv_kind(max(hv_n, 1))
  character(len=hv_pl), save :: hv_pat(max(hv_n, 1))
  integer, save :: hv_cur = 1
  integer, save :: hv_nots(4096)
  integer, save :: hv_nnots = 0
end module hv_state

module hv_selfcheck
  use, intrinsic :: iso_c_binding
  use omp_lib
  use hv_state
  implicit none
@@REQUIRES@@
  private
  public :: hv_begin, hv_end
  interface
    function c_dup(fd) bind(c, name='dup') result(r)
      import :: c_int
      integer(c_int), value :: fd
      integer(c_int) :: r
    end function
    function c_dup2(a, b) bind(c, name='dup2') result(r)
      import :: c_int
      integer(c_int), value :: a, b
      integer(c_int) :: r
    end function
    function c_creat(path, mode) bind(c, name='creat') result(r)
      import :: c_int, c_char
      character(kind=c_char) :: path(*)
      integer(c_int), value :: mode
      integer(c_int) :: r
    end function
    function c_close(fd) bind(c, name='close') result(r)
      import :: c_int
      integer(c_int), value :: fd
      integer(c_int) :: r
    end function
    function c_unlink(path) bind(c, name='unlink') result(r)
      import :: c_int, c_char
      character(kind=c_char) :: path(*)
      integer(c_int) :: r
    end function
    function c_getpid() bind(c, name='getpid') result(r)
      import :: c_int
      integer(c_int) :: r
    end function
    function c_fflush(f) bind(c, name='fflush') result(r)
      import :: c_int, c_ptr
      type(c_ptr), value :: f
      integer(c_int) :: r
    end function
    function c_atexit(f) bind(c, name='atexit') result(r)
      import :: c_int, c_funptr
      type(c_funptr), value :: f
      integer(c_int) :: r
    end function
    function c_fopen(path, mode) bind(c, name='fopen') result(r)
      import :: c_ptr, c_char
      character(kind=c_char) :: path(*), mode(*)
      type(c_ptr) :: r
    end function
    function c_fread(buf, sz, n, f) bind(c, name='fread') result(r)
      import :: c_size_t, c_ptr, c_char
      character(kind=c_char) :: buf(*)
      integer(c_size_t), value :: sz, n
      type(c_ptr), value :: f
      integer(c_size_t) :: r
    end function
    function c_fclose(f) bind(c, name='fclose') result(r)
      import :: c_int, c_ptr
      type(c_ptr), value :: f
      integer(c_int) :: r
    end function
    function c_write(fd, buf, n) bind(c, name='write') result(r)
      import :: c_int, c_size_t, c_long, c_char
      integer(c_int), value :: fd
      character(kind=c_char) :: buf(*)
      integer(c_size_t), value :: n
      integer(c_long) :: r
    end function
  end interface
contains
  subroutine hv_data()
@@SET@@
  end subroutine hv_data

  subroutine hv_say(s)
    character(len=*), intent(in) :: s
    integer(c_long) :: r
    r = c_write(1_c_int, s // achar(10), int(len(s) + 1, c_size_t))
  end subroutine hv_say

  subroutine hv_begin()
    integer :: h(1), fd, r
    character(len=16) :: pid
    h(1) = 1
!$omp target
    if (omp_is_initial_device()) then
      h(1) = 1
    else
      h(1) = 0
    end if
!$omp end target
    hv_host = h(1)
    flush(6)
    r = c_fflush(c_null_ptr)
    write(pid, '(i0)') c_getpid()
    hv_path = 'hv_capture_' // trim(pid) // '.txt'
    fd = c_creat(trim(hv_path) // c_null_char, int(384, c_int))
    if (fd < 0) return
    hv_out = c_dup(1_c_int)
    r = c_dup2(fd, 1_c_int)
    if (hv_merge == 1) then
      hv_err = c_dup(2_c_int)
      r = c_dup2(fd, 2_c_int)
    end if
    r = c_close(fd)
    r = c_atexit(c_funloc(hv_atexit))
  end subroutine hv_begin

  subroutine hv_atexit() bind(c)
    call hv_end()
  end subroutine hv_atexit

  ! the captured output (hv_text) and its token stream without commas
  subroutine hv_read(ok)
    logical, intent(out) :: ok
    type(c_ptr) :: f
    character(kind=c_char), allocatable :: chunk(:)
    integer(c_size_t) :: got
    integer :: k, r, n, i, a, b
    ok = .false.
    hv_text = ''
    f = c_fopen(trim(hv_path) // c_null_char, 'r' // c_null_char)
    if (.not. c_associated(f)) return
    allocate(chunk(65536))
    do
      got = c_fread(chunk, 1_c_size_t, 65536_c_size_t, f)
      if (got <= 0) exit
      n = len(hv_text)
      hv_text = hv_text // repeat(' ', int(got))
      do k = 1, int(got)
        hv_text(n + k:n + k) = chunk(k)
      end do
    end do
    r = c_fclose(f)
    r = c_unlink(trim(hv_path) // c_null_char)
    ok = .true.
    n = len(hv_text)
    allocate(hv_ts(n + 1), hv_te(n + 1))
    hv_nt = 0
    i = 1
    do while (hv_tok(hv_text, i, a, b))
      i = b
      if (hv_text(a:b - 1) == ',') cycle
      hv_nt = hv_nt + 1
      hv_ts(hv_nt) = a
      hv_te(hv_nt) = b
    end do
    call hv_repeats()
  end subroutine hv_read

  ! a repeat count r of the token at k (r*c, no blanks), else 0
  integer function hv_rep(k)
    integer, intent(in) :: k
    integer :: j
    hv_rep = 0
    if (k + 2 > hv_nt) return
    if (hv_te(k) - hv_ts(k) > 9) return
    if (verify(hv_text(hv_ts(k):hv_te(k) - 1), '0123456789') /= 0) return
    if (hv_text(hv_ts(k + 1):hv_te(k + 1) - 1) /= '*') return
    if (hv_te(k) /= hv_ts(k + 1) .or. hv_te(k + 1) /= hv_ts(k + 2)) return
    if (hv_text(hv_ts(k + 2):hv_te(k + 2) - 1) == '*') return
    do j = hv_ts(k), hv_te(k) - 1
      hv_rep = hv_rep * 10 + (iachar(hv_text(j:j)) - 48)
    end do
  end function hv_rep

  ! list-directed repeat counts: r*c is r tokens c (F2018 13.10.4)
  subroutine hv_repeats()
    integer, allocatable :: s2(:), e2(:)
    integer :: k, r, n2, j
    n2 = 0
    k = 1
    do while (k <= hv_nt)
      r = hv_rep(k)
      if (r > 0) then
        n2 = n2 + r
        k = k + 3
      else
        n2 = n2 + 1
        k = k + 1
      end if
    end do
    allocate(s2(max(n2, 1)), e2(max(n2, 1)))
    n2 = 0
    k = 1
    do while (k <= hv_nt)
      r = hv_rep(k)
      if (r > 0) then
        do j = 1, r
          n2 = n2 + 1
          s2(n2) = hv_ts(k + 2)
          e2(n2) = hv_te(k + 2)
        end do
        k = k + 3
      else
        n2 = n2 + 1
        s2(n2) = hv_ts(k)
        e2(n2) = hv_te(k)
        k = k + 1
      end if
    end do
    call move_alloc(s2, hv_ts)
    call move_alloc(e2, hv_te)
    hv_nt = n2
  end subroutine hv_repeats

  ! echo the captured lines (at most 300, 200 characters each)
  subroutine hv_echo()
    integer :: i, j, n, k
    n = len(hv_text)
    i = 1
    k = 0
    do while (i <= n .and. k < 300)
      j = index(hv_text(i:), achar(10))
      if (j == 0) then
        j = n + 1
      else
        j = i + j - 1
      end if
      call hv_say('HV| ' // hv_text(i:min(j - 1, i + 199)))
      k = k + 1
      i = j + 1
    end do
  end subroutine hv_echo

  pure logical function hv_isdigit(c)
    character, intent(in) :: c
    hv_isdigit = c >= '0' .and. c <= '9'
  end function

  pure logical function hv_isalpha(c)
    character, intent(in) :: c
    hv_isalpha = (c >= 'a' .and. c <= 'z') .or. (c >= 'A' .and. c <= 'Z') &
                 .or. c == '_'
  end function

  pure logical function hv_isspace(c)
    character, intent(in) :: c
    hv_isspace = c == ' ' .or. iachar(c) == 9 .or. iachar(c) == 10 .or. &
                 iachar(c) == 11 .or. iachar(c) == 12 .or. iachar(c) == 13
  end function

  character function hv_char_at(s, i)
    character(len=*), intent(in) :: s
    integer, intent(in) :: i
    if (i >= 1 .and. i <= len(s)) then
      hv_char_at = s(i:i)
    else
      hv_char_at = achar(0)
    end if
  end function

  logical function hv_digit_at(s, i)
    character(len=*), intent(in) :: s
    integer, intent(in) :: i
    hv_digit_at = .false.
    if (i >= 1 .and. i <= len(s)) hv_digit_at = hv_isdigit(s(i:i))
  end function

  ! the next token of s at or after i: s(st:en-1); .false. at the end
  logical function hv_tok(s, i0, st, en)
    character(len=*), intent(in) :: s
    integer, intent(in) :: i0
    integer, intent(out) :: st, en
    integer :: i, j, n
    n = len(s)
    i = i0
    hv_tok = .false.
    st = 0
    en = 0
    do while (i <= n)
      if (.not. hv_isspace(s(i:i))) exit
      i = i + 1
    end do
    if (i > n) return
    hv_tok = .true.
    st = i
    if (hv_isdigit(s(i:i)) .or. (s(i:i) == '.' .and. &
        hv_digit_at(s, i + 1))) then
      if (s(i:i) == '.') then
        i = i + 1
        do while (hv_digit_at(s, i))
          i = i + 1
        end do
      else
        do while (hv_digit_at(s, i))
          i = i + 1
        end do
        if (hv_char_at(s, i) == '.') then
          i = i + 1
          do while (hv_digit_at(s, i))
            i = i + 1
          end do
        end if
      end if
      if (i <= n) then
        if (index('eEdD', s(i:i)) > 0) then
          j = i + 1
          if (hv_char_at(s, j) == '+' .or. hv_char_at(s, j) == '-') j = j + 1
          if (hv_digit_at(s, j)) then
            do while (hv_digit_at(s, j))
              j = j + 1
            end do
            i = j
          end if
        end if
      end if
    else if (hv_isalpha(s(i:i))) then
      do while (i <= n)
        if (.not. (hv_isalpha(s(i:i)) .or. hv_isdigit(s(i:i)))) exit
        i = i + 1
      end do
    else
      i = i + 1
    end if
    en = i
  end function hv_tok

  ! 0 number, 1 word, 2 punctuation
  integer function hv_tkind(t)
    character(len=*), intent(in) :: t
    if (hv_isdigit(t(1:1)) .or. (t(1:1) == '.' .and. len(t) > 1)) then
      hv_tkind = 0
    else if (hv_isalpha(t(1:1))) then
      hv_tkind = 1
    else
      hv_tkind = 2
    end if
  end function

  logical function hv_intlike(t)
    character(len=*), intent(in) :: t
    hv_intlike = scan(t, '.eEdD') == 0
  end function

  real(8) function hv_val(t)
    character(len=*), intent(in) :: t
    integer :: k, nf, ex, sg
    real(8) :: m
    logical :: frac
    m = 0
    nf = 0
    ex = 0
    sg = 1
    frac = .false.
    k = 1
    do while (k <= len(t))
      if (hv_isdigit(t(k:k))) then
        m = m * 10 + (iachar(t(k:k)) - 48)
        if (frac) nf = nf + 1
      else if (t(k:k) == '.') then
        frac = .true.
      else
        exit
      end if
      k = k + 1
    end do
    if (k <= len(t)) then
      k = k + 1
      if (k <= len(t)) then
        if (t(k:k) == '-') sg = -1
        if (t(k:k) == '-' .or. t(k:k) == '+') k = k + 1
      end if
      do while (k <= len(t))
        ex = ex * 10 + (iachar(t(k:k)) - 48)
        k = k + 1
      end do
    end if
    hv_val = m * 10.0d0 ** (sg * ex - nf)
  end function hv_val

  logical function hv_teq(p, o)
    character(len=*), intent(in) :: p, o
    integer :: a, b
    real(8) :: x, y
    if (hv_tkind(p) == 0 .and. hv_tkind(o) == 0) then
      if (hv_intlike(p) .and. hv_intlike(o)) then
        a = verify(p, '0')
        b = verify(o, '0')
        if (a == 0 .and. b == 0) then
          hv_teq = .true.
        else if (a == 0 .or. b == 0) then
          hv_teq = .false.
        else
          hv_teq = len(p) - a == len(o) - b
          if (hv_teq) hv_teq = p(a:) == o(b:)
        end if
        return
      end if
      x = hv_val(p)
      y = hv_val(o)
      hv_teq = x == y .or. abs(x - y) <= 1.0d-5 * max(abs(x), abs(y))
      return
    end if
    hv_teq = len(p) == len(o)
    if (hv_teq) hv_teq = p == o
  end function hv_teq

  ! where: 0 only, 1 first, 2 last, 3 middle
  logical function hv_tok_ok(p, o, where)
    character(len=*), intent(in) :: p, o
    integer, intent(in) :: where
    if (hv_tkind(p) == 1 .and. hv_tkind(o) == 1) then
      if (where == 0) then
        hv_tok_ok = index(o, p) > 0
        return
      else if (where == 1) then
        hv_tok_ok = .false.
        if (len(o) >= len(p)) hv_tok_ok = o(len(o) - len(p) + 1:) == p
        return
      else if (where == 2) then
        hv_tok_ok = .false.
        if (len(o) >= len(p)) hv_tok_ok = o(1:len(p)) == p
        return
      end if
    end if
    hv_tok_ok = hv_teq(p, o)
  end function hv_tok_ok

  ! a segment's tokens (no commas) in the output stream at or after token
  ! c: tokens ms .. me-1
  logical function hv_find_seg(seg, c, ms, me)
    character(len=*), intent(in) :: seg
    integer, intent(in) :: c
    integer, intent(out) :: ms, me
    integer :: np, i, j, where, a, b, k
    integer, allocatable :: ps(:), pe(:)
    logical :: ok
    allocate(ps(len(seg) + 1), pe(len(seg) + 1))
    np = 0
    k = 1
    do while (hv_tok(seg, k, a, b))
      k = b
      if (seg(a:b - 1) == ',') cycle
      np = np + 1
      ps(np) = a
      pe(np) = b
    end do
    hv_find_seg = .false.
    ms = c
    me = c
    if (np == 0) then
      hv_find_seg = .true.
      return
    end if
    do i = c, hv_nt - np + 1
      ok = .true.
      do j = 1, np
        if (np == 1) then
          where = 0
        else if (j == 1) then
          where = 1
        else if (j == np) then
          where = 2
        else
          where = 3
        end if
        ok = hv_tok_ok(seg(ps(j):pe(j) - 1), &
                       hv_text(hv_ts(i + j - 1):hv_te(i + j - 1) - 1), where)
        if (.not. ok) exit
      end do
      if (ok) then
        ms = i
        me = i + np
        hv_find_seg = .true.
        return
      end if
    end do
  end function hv_find_seg

  logical function hv_find(k, from, ms, me)
    integer, intent(in) :: k, from
    integer, intent(out) :: ms, me
    integer :: p, q, c, s, e, start
    character(len=:), allocatable :: pat
    pat = trim(hv_pat(k))
    start = -1
    c = from
    p = 1
    hv_find = .false.
    ms = from
    me = from
    do
      q = index(pat(p:), achar(2))
      if (q == 0) then
        q = len(pat) + 1
      else
        q = p + q - 1
      end if
      if (q > p) then
        if (len_trim(pat(p:q - 1)) > 0) then
          if (.not. hv_find_seg(pat(p:q - 1), c, s, e)) return
          if (start < 0) start = s
          c = e
        end if
      end if
      if (q > len(pat)) exit
      p = q + 1
    end do
    hv_find = .true.
    if (start >= 0) then
      ms = start
      me = c
    end if
  end function hv_find

  ! the first pending CHECK-NOT that occurs before token `limit`, else 0
  integer function hv_bad_not(limit)
    integer, intent(in) :: limit
    integer :: k, s, e
    hv_bad_not = 0
    do k = 1, hv_nnots
      if (hv_find(hv_nots(k), hv_cur, s, e)) then
        if (e <= limit) then
          hv_bad_not = hv_nots(k)
          return
        end if
      end if
    end do
  end function hv_bad_not

  logical function hv_match(why)
    character(len=*), intent(out) :: why
    integer :: i, j, k, s, e, bad, mins, maxe
    hv_match = .false.
    why = ' '
    hv_cur = 1
    hv_nnots = 0
    i = 1
    do while (i <= hv_n)
      k = hv_kind(i)
      if (k == 5) then
        i = i + 1
        cycle
      end if
      if (k == 3) then
        if (hv_nnots < 4096) then
          hv_nnots = hv_nnots + 1
          hv_nots(hv_nnots) = i
        end if
        i = i + 1
        cycle
      end if
      if (k == 4) then
        j = i
        mins = huge(1)
        maxe = -1
        do while (j <= hv_n)
          if (hv_kind(j) /= 4) exit
          if (.not. hv_find(j, hv_cur, s, e)) then
            why = 'CHECK-DAG not found: ' // trim(hv_pat(j))
            return
          end if
          mins = min(mins, s)
          maxe = max(maxe, e)
          j = j + 1
        end do
        bad = hv_bad_not(mins)
        if (bad > 0) then
          why = 'CHECK-NOT found: ' // trim(hv_pat(bad))
          return
        end if
        hv_nnots = 0
        hv_cur = maxe
        i = j
        cycle
      end if
      if (.not. hv_find(i, hv_cur, s, e)) then
        why = 'not found: ' // trim(hv_pat(i))
        return
      end if
      bad = hv_bad_not(s)
      if (bad > 0) then
        why = 'CHECK-NOT found: ' // trim(hv_pat(bad))
        return
      end if
      hv_nnots = 0
      hv_cur = e
      i = i + 1
    end do
    bad = hv_bad_not(hv_nt + 1)
    if (bad > 0) then
      why = 'CHECK-NOT found: ' // trim(hv_pat(bad))
      return
    end if
    hv_match = .true.
  end function hv_match

  subroutine hv_end()
    integer :: r
    logical :: ok, got
    character(len=600) :: why
    if (hv_done) return
    hv_done = .true.
    flush(6)
    r = c_fflush(c_null_ptr)
    if (hv_out >= 0) r = c_dup2(hv_out, 1_c_int)
    if (hv_err >= 0) r = c_dup2(hv_err, 2_c_int)
    call hv_data()
    call hv_read(got)
    if (.not. got) then
      allocate(hv_ts(1), hv_te(1))
      hv_nt = 0
    end if
    call hv_echo()
    ok = .false.
    if (got) then
      ok = hv_match(why)
    else
      why = 'the captured output is missing'
    end if
    if (.not. ok) call hv_say('HV-FAIL ' // trim(why(1:150)))
    if (ok) then
      call hv_say('RESULT ran_on_host=' // achar(48 + hv_host) // ' check=pass')
    else
      call hv_say('RESULT ran_on_host=' // achar(48 + hv_host) // ' check=fail')
    end if
  end subroutine hv_end
end module hv_selfcheck

program hv_main
  use hv_selfcheck
  implicit none
  call hv_begin()
  call hv_orig_main()
  call hv_end()
end program hv_main
"""
