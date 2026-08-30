from pathlib import Path


ROOT = Path(__file__).parents[1]
GUEST = ROOT / "guest" / "windows98" / "retrobridge98"


def test_guest_protocol_constants_match_host_extension_numbers() -> None:
    header = (GUEST / "rbproto.h").read_text(encoding="ascii")
    assert "#define RB_MSG_PEER_INFO 19" in header
    assert "#define RB_MSG_FAVORITES_STATE 20" in header
    assert "#define RB_MSG_DOWNLOAD_HISTORY_REQUEST 21" in header
    assert "#define RB_MSG_DOWNLOAD_HISTORY 22" in header


def test_guest_installer_keeps_autostart_explicit_and_reversible() -> None:
    installer = (GUEST / "INSTALL.VBS").read_text(encoding="ascii")
    uninstaller = (GUEST / "UNINSTALL.VBS").read_text(encoding="ascii")
    helper = (GUEST / "AUTOSTRT.VBS").read_text(encoding="ascii")
    assert "Choose No to keep launching it manually" in installer
    assert "292" in installer
    assert 'action = "enable"' in helper
    assert 'action = "disable"' in helper
    assert 'SpecialFolders("Startup")' in uninstaller


def test_resource_dialogs_are_linked_into_the_guest_binary() -> None:
    makefile = (GUEST / "Makefile.mingw").read_text(encoding="ascii")
    resources = (GUEST / "retrobridge98.rc").read_text(encoding="ascii")
    assert "i686-w64-mingw32-windres" in makefile
    assert "IDD_TEXT_PROMPT" in resources
    assert "IDD_FAVORITES" in resources
    assert "IDD_DOWNLOAD_HISTORY" in resources


def test_address_and_find_submit_on_translated_return_character() -> None:
    source = (GUEST / "retrobridge98.c").read_text(encoding="ascii")
    assert source.count("message == WM_CHAR && wparam == '\\r'") == 2
    assert source.count("message == WM_KEYDOWN && wparam == VK_RETURN") == 2
