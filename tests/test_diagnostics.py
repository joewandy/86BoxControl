from pathlib import Path

from retrobridge.diagnostics import pairing_status


def test_pairing_diagnostics_never_disclose_token(tmp_path: Path) -> None:
    token = "0123456789abcdef0123456789abcdef"
    token_path = tmp_path / "retrobridge.token"
    ini_path = tmp_path / "retrobridge.ini"
    token_path.write_text(token + "\n", encoding="ascii")
    ini_path.write_text(
        "[RetroBridge]\nServer=10.0.2.2\nPort=9866\nToken=" + token + "\n",
        encoding="ascii",
    )
    payload = pairing_status(token_path=token_path, ini_path=ini_path)
    assert payload["ready"]
    assert token not in repr(payload)


def test_pairing_diagnostics_detect_mismatch(tmp_path: Path) -> None:
    token_path = tmp_path / "retrobridge.token"
    ini_path = tmp_path / "retrobridge.ini"
    token_path.write_text("0" * 32, encoding="ascii")
    ini_path.write_text(
        "[RetroBridge]\nServer=10.0.2.2\nPort=9866\nToken=" + "1" * 32,
        encoding="ascii",
    )
    assert not pairing_status(token_path=token_path, ini_path=ini_path)["ready"]
