"""tools/repo/scrub_vocab.py: process labels out of comments, docstrings and prose; meaning stays."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]

import scrub_vocab as SV  # noqa: E402


def test_a_leading_label_goes_and_the_sentence_starts_with_a_capital():
    assert SV.scrub("# Task 24: the self clause in its update form") == "# The self clause in its update form"
    assert SV.scrub('"""Task 24: the if clause judged on a data directive.') == '"""The if clause judged on a data directive.'
    assert SV.scrub("# Task 38a fix round 1 (review C1, I1, I7): what a scorer reads") == "# What a scorer reads"
    assert SV.scrub("# Task 49c review I5: the holdout rows") == "# The holdout rows"


def test_a_label_only_line_is_dropped_but_a_rule_line_keeps_its_dashes():
    assert SV.scrub("# --- Task 51 fix round 2 (review I4) ---") == ""
    assert SV.scrub("# --- Task 51: the ptxas patterns ---") == "# --- The ptxas patterns ---"


def test_a_trailing_parenthetical_label_is_removed():
    assert SV.scrub("x = 1  # the loop (Task 38b)") == "x = 1  # the loop"
    assert SV.scrub("the loop (fix round 1, review I2) runs") == "the loop runs"
    assert SV.scrub("the loop (fix round 1, review I2, covers the case) runs") == "the loop (covers the case) runs"
    assert SV.scrub("see rule (Task 31, rulings.md) now") == "see rule (rulings.md) now"


def test_mid_sentence_mentions_read_naturally():
    assert SV.scrub("rerun in full in fix round 1, then stop") == "rerun in full, then stop"
    assert SV.scrub("widened since Task 16 to cover it") == "widened to cover it"
    assert SV.scrub("the Task 33 rows") == "the rows"
    assert SV.scrub("the Task 30 follow-up and a Task 22 rerun") == "the follow-up and a rerun"


def test_working_vocabulary_is_rewritten_and_technical_uses_stay():
    assert SV.scrub("the owner decides") == "the maintainer decides"
    assert SV.scrub("an owner ruling of 2026-10-21") == "a maintainer ruling of 2026-10-21"
    assert SV.scrub("the coordinator sends it") == "the maintainer sends it"
    assert SV.scrub("a pilot of 20 programs") == "a trial of 20 programs"
    assert SV.scrub("a pilot signal") == "a pilot signal"      # not followed by a counted object: left for review


def test_text_without_vocabulary_is_returned_unchanged():
    for s in ("# nothing here", "x = 'Task'", "tasks = []", "the taskset runs", "Task manager"):
        assert SV.scrub(s) == s


def test_residue_lists_what_the_rules_do_not_handle():
    assert SV.residue("fine text") == []
    assert SV.residue("odd Task 7's quirk") == ["Task 7"]


def test_possessives_dangling_words_and_stage_numbers_are_cleaned_up():
    assert SV.scrub("(Task 49a's seal)") == "(the seal)"
    assert SV.scrub("a thing ('s decisions)") == "a thing (the decisions)"
    assert SV.scrub("Probes (Task 37; rerun in full in fix round 1, tools/x/)") == "Probes (rerun in full, tools/x/)"
    assert SV.scrub("(outside the kernels; Task 23 stage 5)") == "(outside the kernels)"
    assert SV.scrub("an earlier step fix: x and an earlier step follow-up") == "fix: x and follow-up"


def test_string_values_and_yaml_values_lose_their_label_too():
    assert SV.scrub('help="Task 38b: run no compile"') == 'help="Run no compile"'
    assert SV.scrub("  reason: \"Task 27b: the p\"") == "  reason: \"The p\""
    assert SV.scrub("- 'R22b (Task 28): a run-time failure'") == "- 'R22b: a run-time failure'"


def test_strings_in_python_are_scrubbed_but_not_code_and_the_guard_checks_it():
    src = 'HELP = "Task 3: a thing"\nx = 1  # Task 3: note\nSEAL = ("seal",)\n'
    new = SV.scrub_source("a.py", src, strings=True)
    assert new == 'HELP = "A thing"\nx = 1  # Note\nSEAL = ("seal",)\n'
    assert SV.only_strings_changed(src, new)
    assert not SV.only_strings_changed(src, new.replace("x = 1", "x = 2"))


def test_files_that_write_the_committed_seals_keep_their_strings():
    src = 'S = "# Task 38a seal\\n"\n'
    assert SV.scrub_source("offload/engine/harvest2/split.py", src, strings=True) == src


def test_a_comment_marker_right_after_a_quote_is_still_a_leading_label():
    assert SV.scrub('"""# Task 31 fix round 1: C ports') == '"""# C ports'


def test_remaining_working_words_are_rewritten_in_both_cases():
    assert SV.scrub("# Owner ruling 2026-10-23 (final)") == "# Maintainer ruling 2026-10-23 (final)"
    assert SV.scrub("Owner decisions still open") == "Maintainer decisions still open"
    assert SV.scrub("coordinator's ruling and the Coordinator") == "maintainer's ruling and the Maintainer"
    assert SV.scrub("list-directed repeat count;, errata item 16) now") == "list-directed repeat count;, a correction) now"
    assert SV.scrub("(errata item 11): the finding is AFAR") == ": the finding is AFAR"
    assert SV.scrub("correct on the pilot's module form; The pilot ran") == "correct on the trial's module form; The trial ran"


def test_json_string_values_are_scrubbed_and_the_document_is_otherwise_identical():
    old = '{"note": "Task 39 usage profile (Task 39, fix round 1) of apps", "n": 3, "k": ["Task 7: a list item"]}'
    new = SV.scrub_source("a.json", old, strings=True)
    import json
    assert json.loads(new) == {"note": "Usage profile of apps", "n": 3, "k": ["A list item"]}
    assert new.count("{") == 1 and new.endswith("]}")


def test_f_strings_and_adjacent_literals_are_scrubbed_and_the_code_shape_is_kept():
    src = 'mark = f"! Task 49c: appended {path}"\nWHY = ("added in Task 27b "\n       "to judge")\n'
    new = SV.scrub_source("a.py", src, strings=True)
    assert 'f"! Appended {path}"' in new.replace("! An earlier step: appended", "! Appended") or "Task 49c" not in new
    assert "Task 27b" not in new and SV.only_strings_changed(src, new)


def test_shell_why_strings_are_scrubbed_but_other_lines_are_not():
    sh = 'WHY="Task 27a: oracle hardening"\ngrep -q "Task 41 o0cbc" CMakeLists.txt\n# Task 3: a comment\n'
    new = SV.scrub_source("a.sh", sh, strings=True)
    assert new == 'WHY="Oracle hardening"\ngrep -q "Task 41 o0cbc" CMakeLists.txt\n# A comment\n'


def test_trailing_shell_comments_and_yaml_label_lines():
    sh = 'x) A="--lang c" ;;  # Task 37: C 5.0\ny) echo "a # b" # Task 3: kept\n'
    assert SV.scrub_source("a.sh", sh, strings=True) == 'x) A="--lang c" ;;  # C 5.0\ny) echo "a # b" # Kept\n'
    y = "a: 1\n# --- Task 27b ---------------\nb: 2\n"
    assert SV.scrub_source("a.yaml", y, strings=True) == "a: 1\nb: 2\n"


def test_c_block_comments_are_scrubbed():
    src = "/* Task 20 finding (C): a thing */\nint x; /* keep */\n/* # Finding (Task 47, lead 2): AFAR drops it\n   (errata item 10): and the Task 46 pilot saw it */\n"
    new = SV.scrub_source("a.c", src)
    assert new.startswith("/* Finding (C): a thing */\nint x; /* keep */\n/* # Finding (lead 2): AFAR drops it")
    assert "Task" not in new and "errata" not in new and "pilot" not in new


def test_labels_inside_parentheses_leave_the_rest_of_the_sentence_intact():
    # words like "review" and "round" are ordinary English; only label tokens go
    assert SV.scrub("(-119, 94; the Task 46 pilot saw 104; the Task 47 review's 12 runs all printed 0)") == \
        "(-119, 94; the trial saw 104; the review's 12 runs all printed 0)"
    assert SV.scrub("(a Task 12 rule)") == "(a rule)"
    assert SV.scrub("(Task 30: afar -> afar_g90)") == "(afar -> afar_g90)"
    assert SV.scrub("(the finding: bad= 16, Task 47 fix round 2 sees it)") == "(the finding: bad= 16, sees it)"


def test_possessive_labels_do_not_leave_a_bare_apostrophe_s():
    assert SV.scrub("# Task 45's decisions on the queue") == "# The decisions on the queue"
    assert SV.scrub("adds one, e.g. Task 43's dataenv kind") == "adds one, e.g. dataenv kind"


def test_a_sentence_that_starts_with_a_label_loses_it():
    assert SV.scrub("reduced by hand. Task 47 (errata item 11): that rejection stayed") == \
        "reduced by hand. That rejection stayed"


def test_a_label_that_introduces_a_colon_just_drops():
    assert SV.scrub("lang: f90  # Task 33: a Fortran sentence") == "lang: f90  # A Fortran sentence"
    assert SV.scrub("(Task 14: none recorded; Task 15: foo)") == "(none recorded; foo)"
    assert SV.scrub("x = 1  // Task 3: note here") == "x = 1  // Note here"


def test_a_label_before_a_noun_drops_and_one_after_a_preposition_becomes_a_step():
    assert SV.scrub("(OpenMP 5.2, C11; Task 35 catalog widening)") == "(OpenMP 5.2, C11; catalog widening)"
    assert SV.scrub("a campaign recorded before Task 17 has no canaries") == \
        "a campaign recorded has no canaries"
    assert SV.scrub("(NO_ORACLE, Task 15; Task 27b)") == "(NO_ORACLE)"
    assert SV.scrub("# the maintainer, Task 33: the C nohost programs") == "# the maintainer, the C nohost programs"
    assert SV.scrub("see Task 9c probes and Task 12 rerun") == "see probes and rerun"


def test_plural_rounds_and_the_engine_module():
    assert SV.scrub("Reduced in fix rounds 1 and 2 (tools/x/)") == "Reduced (tools/x/)"
    from offload.engine import textclean
    assert textclean.scrub is SV.scrub and textclean.residue is SV.residue


def test_a_bare_round_number_is_ordinary_text():
    assert SV.scrub("gcc_probe --rounds 4 --timeout 60") == "gcc_probe --rounds 4 --timeout 60"
    assert SV.residue("--rounds 4 and round 2") == []


def test_an_old_tools_script_path_in_a_run_note_names_its_new_home():
    from offload.engine.textclean import scrub
    assert scrub("whole catalog on every toolchain (" + "tools/" + "regenerate.py)") == "whole catalog on every toolchain (tools/regenerate.py)"
    assert scrub("see site/tools/x.js") == "see site/tools/x.js"


def test_a_dropped_label_does_not_glue_a_relative_path_to_the_word_before_it():
    from offload.engine.textclean import scrub
    assert scrub("per group of ./mfc.sh test, the rest") == "per group of ./mfc.sh test, the rest"
    assert scrub("see Task 5 .") == "see."
