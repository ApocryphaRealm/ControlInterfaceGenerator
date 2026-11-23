"""build_exe refuses to bundle a file that carries an absolute Windows path (rule 45: no build-machine path ships)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_exe  # noqa: E402


def _scan(tmp_path, monkeypatch, data: bytes):
    (tmp_path / "cig").mkdir()
    (tmp_path / "cig" / "x.py").write_bytes(data)
    monkeypatch.setattr(build_exe, "REPO", tmp_path)
    return build_exe.machine_paths()


def test_a_drive_path_is_found(tmp_path, monkeypatch):
    assert _scan(tmp_path, monkeypatch, b'P = r"D:\\Some folder\\x.json"\n')


def test_a_utf16_drive_path_is_found(tmp_path, monkeypatch):
    assert _scan(tmp_path, monkeypatch, "C:\\Users\\someone".encode("utf-16-le"))


def test_a_regex_after_a_word_is_not_a_path(tmp_path, monkeypatch):
    assert not _scan(tmp_path, monkeypatch, b'"usage_re": "^Usage:\\\\s*\\\\S+"')


def test_the_real_inputs_are_clean():
    assert build_exe.machine_paths() == []
