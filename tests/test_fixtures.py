from retrobridge.fixtures import SELF_TEST_ORIGIN, fixture_for_url


def test_fixture_pages_are_available_only_on_the_qa_origin() -> None:
    home = fixture_for_url(SELF_TEST_ORIGIN + "/")
    assert home is not None
    assert home.status == 200
    assert b"Open normal link" in home.body
    assert fixture_for_url("https://example.com/") is None


def test_fixture_download_has_a_safe_stable_name() -> None:
    download = fixture_for_url(SELF_TEST_ORIGIN + "/download.bin")
    assert download is not None
    assert download.headers == {
        "Content-Disposition": 'attachment; filename="retrobridge-qa.txt"'
    }


def test_fixture_prompt_page_is_available() -> None:
    prompt = fixture_for_url(SELF_TEST_ORIGIN + "/prompt")
    assert prompt is not None
    assert b"prompt('RetroBridge QA name?', 'Win98')" in prompt.body
