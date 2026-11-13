"""The user's own settings laid over the shared machine and toolchain catalogs (offload.engine.localcfg)."""
import yaml

from offload.engine import localcfg, toolchains
from offload.engine.confirm import machines


def _use(tmp_path, monkeypatch, text):
    f = tmp_path / "local.yaml"
    f.write_text(text)
    monkeypatch.setenv(localcfg.ENV, str(f))
    machines._load_file.cache_clear()
    machines._data.cache_clear()
    toolchains.reset()
    return f


def _clear():
    machines._load_file.cache_clear()
    machines._data.cache_clear()
    toolchains.reset()


def test_mappings_merge_and_null_removes_and_anything_else_replaces():
    base = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": 3}
    assert localcfg.merge(base, {"a": {"y": 5}, "b": [9], "c": None}) == {"a": {"x": 1, "y": 5}, "b": [9]}


def test_without_a_file_the_catalog_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv(localcfg.ENV, str(tmp_path / "missing.yaml"))
    assert localcfg.paths() == []
    monkeypatch.setenv(localcfg.ENV, "")
    assert localcfg.paths() == []
    monkeypatch.delenv(localcfg.ENV)
    monkeypatch.setattr(localcfg, "ROOT", tmp_path)
    monkeypatch.setattr(localcfg.Path, "home", lambda: tmp_path)
    assert localcfg.paths() == []
    assert localcfg.overlay("machines.yaml", {"k": 1}) == {"k": 1}


def test_a_user_adds_a_machine_and_it_is_checked(tmp_path, monkeypatch):
    try:
        _use(tmp_path, monkeypatch, """
machines.yaml:
  machines:
    mybox:
      arch: sm_90
      device: "NVIDIA H100"
      access: local
      scheduler: {kind: local}
      headline_mode: copy
      modes:
        copy: {flags: "-gpu=mem:separate", row_key: 0, target: h100-s,
               target_short: "H100 separate", target_name: "H100, separate memory"}
""")
        got = machines.load()
        assert got["mybox"].arch == "sm_90" and got["mybox"].access == "local"
        assert "tuolumne" in got
    finally:
        monkeypatch.delenv(localcfg.ENV)
        _clear()


def test_a_bad_local_machine_is_refused_like_a_bad_catalog_one(tmp_path, monkeypatch):
    import pytest
    try:
        _use(tmp_path, monkeypatch, "machines.yaml:\n  machines:\n    mybox: {arch: sm_90}\n")
        with pytest.raises(ValueError, match="mybox"):
            machines.load()
    finally:
        monkeypatch.delenv(localcfg.ENV)
        _clear()


def test_a_user_points_a_compiler_at_their_install(tmp_path, monkeypatch):
    try:
        _use(tmp_path, monkeypatch, "toolchains.yaml:\n  toolchains:\n    gcc_g90:\n      install: {default: /somewhere/gcc}\n")
        assert toolchains.registry().toolchains["gcc_g90"].install_root == "/somewhere/gcc"
    finally:
        monkeypatch.delenv(localcfg.ENV)
        _clear()


def test_an_explicit_catalog_path_is_read_as_given(tmp_path, monkeypatch):
    try:
        _use(tmp_path, monkeypatch, "toolchains.yaml:\n  toolchains:\n    gcc_g90:\n      install: {default: /somewhere/gcc}\n")
        copy = tmp_path / "t.yaml"
        copy.write_text(toolchains.CATALOG.read_text())
        assert toolchains.load(copy).toolchains["gcc_g90"].install_root != "/somewhere/gcc"
    finally:
        monkeypatch.delenv(localcfg.ENV)
        _clear()


def test_later_files_are_laid_over_earlier_ones(tmp_path, monkeypatch):
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text("t.yaml: {k: {x: 1, y: 1}}\n")
    b.write_text("t.yaml: {k: {y: 2}}\n")
    monkeypatch.setenv(localcfg.ENV, f"{a}{localcfg.os.pathsep}{b}")
    assert localcfg.overlay("t.yaml", {}) == {"k": {"x": 1, "y": 2}}
