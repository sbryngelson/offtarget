import re
import subprocess
from pathlib import Path
import pytest

from offload.engine import spec_text

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.needs_spec
def test_map_clause_found_60():
    secs = spec_text.sections("6.0")
    assert "map Clause" in secs
    assert "map-type" in secs["map Clause"].text
    assert secs["map Clause"].first_page <= secs["map Clause"].last_page


@pytest.mark.needs_spec
def test_restrictions_nonempty():
    items = spec_text.restrictions("6.0", "target")
    assert items
    for it in items:
        assert re.match(r"^OpenMP 6\.0 §[\d.]+, p\.\d+$", it.citation), it.citation
    assert len({it.text for it in items}) == len(items)
    assert any("ancestor" in it.text for it in items)


@pytest.mark.needs_spec
def test_restrictions_5_2():
    items = spec_text.restrictions("5.2", "target")
    assert items and all(i.citation.startswith("OpenMP 5.2 §") for i in items)


@pytest.mark.needs_spec
def test_toc_does_not_duplicate_sections():
    secs = spec_text.sections("6.0")
    assert all(s.text.strip() for s in secs.values())
    assert secs["target Construct"].first_page > 100


def test_cache_not_in_git():
    r = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "results/spec_cache/x.txt"],
        capture_output=True, text=True)
    assert r.returncode == 0


SLICE = ["target", "target data", "target enter data", "target exit data",
         "target update", "teams", "distribute", "parallel",
         "Worksharing-Loop Constructs", "loop", "declare target", "requires"]
# Sections that exist but have no Restrictions block (verified by hand).
# Verified: these sections contain no "Restrictions" heading in the extracted text.
NO_RESTRICTIONS = {
    ("5.2", "parallel"), ("6.0", "parallel"),
    ("5.2", "target update"), ("6.0", "target update"),
    ("6.0", "target data"),
}
CITE = r"^OpenMP (5\.2|6\.0) §[\d.]+, p\.\d+$"


@pytest.mark.needs_spec
@pytest.mark.parametrize("version", ["5.2", "6.0"])
@pytest.mark.parametrize("name", SLICE)
def test_slice_restrictions(version, name):
    items = spec_text.restrictions(version, name)
    if (version, name) in NO_RESTRICTIONS:
        assert items == []
        return
    assert items, (version, name)
    assert all(re.match(CITE, i.citation) for i in items)


@pytest.mark.needs_spec
def test_unknown_name_raises():
    with pytest.raises(KeyError, match="no_such_construct"):
        spec_text.restrictions("6.0", "no_such_construct")


@pytest.mark.needs_spec
def test_teams_no_split_at_page_break():
    items = spec_text.restrictions("6.0", "teams")
    assert not any(i.text.startswith("used in any clause") for i in items)
    assert any("target-consistent expressions" in i.text
               and i.text.startswith("For a teams construct") for i in items)


# Items that legitimately start lowercase: none expected.
# Exception: 5.2 teams item starting with the directive name "distribute regions".
LOWERCASE_OK = {"distribute regions, including"}


@pytest.mark.needs_spec
@pytest.mark.parametrize("version", ["5.2", "6.0"])
def test_no_item_starts_lowercase(version):
    for name in SLICE + ["map", "reduction"]:
        for i in spec_text.restrictions(version, name):
            assert not i.text[0].islower() or any(i.text.startswith(p) for p in LOWERCASE_OK), (name, i.text[:60])


@pytest.mark.needs_spec
@pytest.mark.parametrize("version", ["5.2", "6.0"])
@pytest.mark.parametrize("name", ["map", "reduction", "map Clause"])
def test_clause_restrictions(version, name):
    items = spec_text.restrictions(version, name)
    assert items and all(re.match(CITE, i.citation) for i in items)


@pytest.mark.needs_spec
def test_chapter_heading_splits_sections():
    assert "Interoperability" not in spec_text.sections("5.2")["target update Construct"].text


@pytest.mark.needs_spec
def test_chapter_opening_page_number():
    # 5.2 chapter 10 opens on printed p.223 (bare-number footer), not the PDF index.
    assert spec_text.sections("5.2")["parallel Construct"].first_page == 223
