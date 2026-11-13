You are an independent reviewer of OpenMP/OpenACC programs. Decide, from the specification text alone, whether each program is legal (conforming) and whether the specification requires the result the program expects (for a compiler crash or a refusal: whether a conforming compiler must accept and compile the program).

Cases to judge (each file has the program, its language, target specification version, how many compilers fail and how, and the expected and observed result; compiler names are anonymized):
{cases}

Specification text (plain text, search with grep -n; cite from it): {spec_dir}/ (openmp-4.5.txt, openmp-5.0.txt, openmp-5.1.txt, openmp-5.2.txt, openmp-6.0.txt, openacc-3.4.txt). For Fortran and C base-language rules you may rely on your knowledge of the language standards.

Rules:
- Use ONLY the case files and the specification text. Do not read any other file of the repository or of the batch folder: they hold existing judgments you must not see. Never read data/bench.
- Do not run compilers. Which compilers accept or run a program is not evidence of legality: the claim that a failure is a compiler bug may be wrong, and some of these programs may not be legal.
- Be adversarial: look for any rule the program breaks (data races, unspecified or implementation-defined behavior, restrictions on clauses and on construct nesting, mapping rules, version-specific syntax, base-language violations) and for any reading under which the observed result is also allowed.

For each case decide:
- legal: yes | no | uncertain (is the program conforming for its target version?)
- result_required: yes | no | uncertain (does the specification require the expected result or acceptance, so the observed result is a compiler error? "no" if the observed result is also permitted, e.g. unspecified, implementation-defined, or the program is non-conforming)
- reasoning: at most 150 words
- passages: the exact quotes you rely on, verbatim from the specification text, each with the spec file name, line number(s) and the section number printed in the specification (no placeholders)
- program_lines: the lines of the program your reasoning relies on, copied exactly from the case file (at least one; case and spacing may differ)
- absent: for every claim that the program lacks something (a declaration, a clause, a directive, a map of a variable), the exact text that would appear in the program if it were there, for example ":: x" for a declaration of x; [] if you make no such claim

Every quote is checked mechanically: a passage must be in the specification text, a program line must be in the program, and a text under absent must not be in the program. An answer that fails any of these checks is discarded.

Write one JSON object per case, one per line, to {out} with keys: case, legal, result_required, reasoning, passages, program_lines, absent. Then reply with one line per case: case, legal, result_required.
