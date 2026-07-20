"""The invite path: owner-chosen passcodes and the invite email itself."""
from app import auth


def test_custom_code_roundtrip(app_env):
    # normalized at creation exactly the way code_login normalizes what people type,
    # so a sloppily-typed version of the same code still lands
    code = auth.normalize_code("sea-breeze 42x")
    assert code == "SEABREEZE42X"
    r = auth.create_key_member("Dad", email="dad@example.com", code=code)
    assert r["code"] == "SEABREEZE42X"
    hit = auth.code_login("sea-breeze 42x")
    assert hit and hit["email"] == "dad@example.com"


def test_generated_code_still_works(app_env):
    r = auth.create_key_member("Bob", email="bob@example.com")
    assert r["code"] and len(r["code"]) == 8
    hit = auth.code_login(r["code"])
    assert hit and hit["email"] == "bob@example.com"


def test_normalize_code_rejects_out_of_range():
    assert auth.normalize_code("abc12") == ""          # 5 after cleanup — too short
    assert auth.normalize_code("x" * 25) == ""         # too long
    assert auth.normalize_code("  ok-code-1  ") == "OKCODE1"


def test_send_key_email_console_backend(app_env):
    # console is a real backend: the whole flow works with no SMTP configured
    assert auth.send_key_email("Dad", "dad@example.com", "https://x/k/tok", "ABC12345")


def test_send_key_email_contains_the_essentials(app_env, monkeypatch):
    from app import mail
    sent = {}
    monkeypatch.setattr(mail, "send", lambda to, subject, body, cc="": sent.update(
        to=to, subject=subject, body=body, cc=cc) or True)
    assert auth.send_key_email("Dad Mimick", "dad@example.com", "https://j/k/tok", "ABC12345",
                               cc="owner@example.com")
    assert sent["to"] == "dad@example.com"
    assert sent["cc"] == "owner@example.com"
    assert "https://j/k/tok" in sent["body"] and "ABC12345" in sent["body"]
    assert sent["body"].startswith("Hi Dad,")
