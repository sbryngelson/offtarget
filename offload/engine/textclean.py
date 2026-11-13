"""Text rules that take the project's internal work-item vocabulary ("Task 38b", "fix round 2", "review I5",
"the owner") out of a comment, docstring or paragraph and keep the sentence's meaning.

`scrub(text)` rewrites; `residue(text)` lists what is left. tools/repo/scrub_vocab.py applies them to files; the
report generators apply them to run notes taken from stored measurements.
"""
import re

LAB = r"Task \d+[a-z]?(?:/\d+[a-z]?)*(?: stage \d+)?"
RND = r"(?:fix |re-)rounds? \d+(?: and \d+)?"
REV = r"(?:re-)?review (?:minor \d+|[CIM]\d+(?:(?:, | and )[CIM]?\d+)*)"
ITEM = rf"(?:{LAB}|{RND}|{REV})"
ITEMS = rf"{ITEM}(?:[ ,]+{ITEM})*"
LABPAREN = r"\((?:[CIMm]\d+|minor \d+|review|round|fix|and|[ ,]|" + ITEM + r")+\)"
FORBIDDEN = re.compile(rf"{LAB}|{RND}|{REV}|errata item|[Cc]oordinator|\b[Tt]he owner\b|\b[Oo]wner(?:'s)? (?:ruling|decision|call|approval)"
                       rf"|\b(?:[Aa]|[Tt]he|[Tt]his) pilot\b")

_Q = r"r?(?:\"\"\"|'''|\"|')"
_LEAD = re.compile(rf"^(?P<pre>[ \t]*(?:(?:-[ \t]+)?[\w.-]+:[ \t]+{_Q}?|[\w.]+[ \t]*=[ \t]*{_Q}|(?:{_Q})?(?:#+[ \t]*(?:---[ \t]*)?|//[ \t]*|/\*+[ \t]*|![ \t]*)|{_Q}|-[ \t]+)?)"
                   rf"(?P<lab>{ITEMS})(?:[ \t]*{LABPAREN})?[ \t]*(?P<sep>[:.,])?[ \t]*(?P<rest>.*)$")
_PAREN = re.compile(r"[ \t]*\(([^()\n]*(?:\n[^()\n]*)*)\)")


def _lead(line: str) -> str | None:
    m = _LEAD.match(line)
    if not m:
        return line
    rest = m.group("rest")
    if not rest.strip(" -#"):
        return None                                   # a line that was only a label
    if rest.startswith("'s "):
        rest = "The" + rest[2:]
    elif rest[0].islower():
        rest = rest[0].upper() + rest[1:]
    return m.group("pre") + rest


_PURE = re.compile(rf"^(?:{ITEM}|[CIMm]\d+|minor \d+|review|round|fix|and|[\s,;])+$")
_LEADING = re.compile(rf"^\s*(?:{ITEMS})(?P<poss>'s)?[\s,;:]*")
_TRAILING = re.compile(rf"[,;][ \t]*(?:{ITEMS})[ \t]*$")


def _paren(m: re.Match) -> str:
    """A parenthetical that is only a label goes; one that starts or ends with a label loses it; others stay."""
    inner = m.group(1)
    lead = re.match(r"[ \t]*", m.group(0)).group(0)
    if not re.search(ITEM, inner):
        return m.group(0)
    if _PURE.match(inner):
        return ""
    lm = _LEADING.match(inner)
    if lm:
        kept = ("the " if lm.group("poss") else "") + inner[lm.end():]
        kept = re.sub(r"^[CIMm]\d+(?:,\s*[CIM]?\d+)*,?\s*", "", kept)
    else:
        kept = _TRAILING.sub("", inner)
    return f"{lead}({kept.strip()})" if kept.strip() else ""


_SENTENCE_START = re.compile(rf"(?P<pre>^|[.!?][ \t]+){LAB}(?:[ \t]*\((?:errata items? \d+|{ITEM}|[CIMm]\d+|[,\s])+\))?[ \t]*[:,]?[ \t]*(?P<c>[A-Za-z])", re.M)


def scrub(text: str) -> str:
    lines = [_lead(l) for l in text.split("\n")]
    text = "\n".join(l for l in lines if l is not None)
    text = _SENTENCE_START.sub(lambda m: m.group("pre") + m.group("c").upper(), text)
    text = re.sub(rf"(?P<pre>(?:#|//|/\*|!)[ \t]+){ITEMS}[ \t]*:[ \t]*(?P<c>[A-Za-z])", lambda m: m.group("pre") + m.group("c").upper(), text)
    text = re.sub(rf"(?<=[;(,])[ \t]*{ITEMS}[ \t]*:[ \t]+", " ", text).replace("( ", "(")
    text = re.sub(rf"[,;][ \t]*{ITEMS}(?=[ \t]*[;,)\]])", "", text)
    text = re.sub(rf"(?<![\w])(?<!since )(?<!before )(?<!after )(?<!until )(?<!during )(?<!of )(?<!at )(?<!from )(?<!by )(?<!in )(?<!to )"
                  rf"(?<!with )(?<!for ){LAB}[ \t]+(?=[a-z])", "", text)
    text = re.sub(rf"\b([Tt]he|a|an)[ \t]+{LAB}[ \t]+(?=[a-z])", r"\1 ", text)
    text = _PAREN.sub(_paren, text)
    text = re.sub(rf"(?:[ \t]+(?:in|after|from|during))?[ \t]+{RND}", "", text)
    text = re.sub(rf"[ \t]+{REV}", "", text)
    text = re.sub(rf"{LAB}[ \t]+(?=(?:fix|fixed|follow-up|rerun|stage|pass|seal|rows|check|gate)\b)", "", text)
    text = re.sub(rf"(?:[ \t]+(?:since|before|after|until|from|during|at|by|in|of|for|with|to))?[ \t]+{LAB}(?:'s)?", "", text)
    text = re.sub(rf"{LAB}(?:'s)?[ \t]*", "", text)
    text = re.sub(r"(?:[ \t]+(?:since|before|after|until|from|during|at|by|in|of|for|with|to))?[ \t]+[Aa]n earlier step(?:'s)?(?![\w-])", "", text)
    text = re.sub(r"\b[Aa]n earlier step(?:'s)?[ \t]*", "", text)
    text = re.sub(r"[ \t]+([,;:)]|\.(?=\s|$))", r"\1", text)
    text = re.sub(r"\(\s*'s\b", "(the", text)
    text = re.sub(r"\(\s*errata items? \d+\s*\)", "", text)
    text = re.sub(r"\berrata items? \d+", "a correction", text)
    text = re.sub(r"(?<![\w/.])tools/(?=[\w.-]+\.(?:py|sh)\b)", "tools/", text)
    text = re.sub(r"\ban owner\b", "a maintainer", text)
    text = re.sub(r"\b([Oo])wner(?=(?:'s)? (?:rulings?|decisions?|calls?|approval|OK|review))", lambda m: "Maintainer" if m.group(1) == "O" else "maintainer", text)
    text = re.sub(r"\b([Cc])oordinator\b", lambda m: "Maintainer" if m.group(1) == "C" else "maintainer", text)
    text = re.sub(r"\b([Tt]he) pilot\b", r"\1 trial", text)
    text = re.sub(r"\b([Tt]he) owner\b", r"\1 maintainer", text)
    text = re.sub(r"\b(a|the) pilot (?=of \d|on \d|with \d)", r"\1 trial ", text)
    return text


def residue(text: str) -> list[str]:
    """The vocabulary still in `text`."""
    return [m.group(0) for m in FORBIDDEN.finditer(text)]
