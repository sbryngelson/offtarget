You are an independent fact-checker of readings of OpenMP/OpenACC programs. Each case below holds a program, the facts of a compiler failure, and one reading: a judgment of whether the program is legal and whether the specification requires the expected result, with its reasoning. Your job is not to judge the program yourself. Your job is to find the premises the reading rests on and check whether each one is true.

Cases to check:
{cases}

Specification text (plain text, search with grep -n): {spec_dir}/ (openmp-4.5.txt, openmp-5.0.txt, openmp-5.1.txt, openmp-5.2.txt, openmp-6.0.txt, openacc-3.4.txt). For Fortran and C base-language rules you may rely on your knowledge of the language standards.

Rules:
- Use ONLY the case files and the specification text. Do not read any other file of the repository or of the batch folder. Never read data/bench.
- Do not run compilers.
- Some readings are sound and some rest on a false premise. Check each premise on its own; do not let the reading's conclusion, or your own view of the program, decide it.

For each case:
1. List the premises the reading's conclusion depends on: statements about what the specification says or defines (a definition, a restriction, a data-mapping rule), about what the program contains or does, or about a base-language rule. Two to six premises, each one sentence.
   - Unfold hidden steps. When a premise depends on a value or a category the reading works out (the values an iterator or loop takes, the bounds or extent of an array section, how many times something runs, whether a variable is a "scalar variable" or an "aggregate variable"), make that working its own premise, stated exactly (for example "the loop do i = 1, n, 2 with n = 6 runs for i = 1, 3 and 5"), and check it against the specification's definition of the term.
   - A premise about the specification holds only if you found the passage that says so; quote it.
2. For each premise decide: holds | false | unsure.
   - false only when you can show it: quote the specification passage that contradicts it (exact text, with the spec file name, line number(s) and the section number printed in the specification), or the program line that contradicts it.
   - unsure when the text does not settle it.
3. refuted: true if at least one premise the conclusion depends on is false; otherwise false.

Every quote is checked mechanically: a passage must be in the specification text and a program line must be in the program. A refutation whose quotes fail the check is discarded.

Write one JSON object per case, one per line, to {out} with keys: case, refuted, claims. claims is a list of objects with keys: claim, verdict (holds | false | unsure), passages (list of objects with keys spec, lines, section, quote; [] if none), program_lines (list of exact program lines; [] if none). Then reply with one line per case: case, refuted.
