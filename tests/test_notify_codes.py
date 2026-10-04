"""Offline tests for the Discord giftcode notifier.

All network access is replaced with FakeResponse objects; nothing here touches
the real Hoyocodes API, Discord, or the network. The state file is exercised
via tmp_path so tests never write to the repo checkout.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import notify_codes as nc


class FakeResponse:
    def __init__(self, status=200, payload=None, retry_after=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = {"Retry-After": retry_after} if retry_after else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


FAKE_GET = {
    "genshin": [
        {"code": "GEN-1", "description": "Mora*50000;Primogem*60", "expires": "2026-12-31T23:59:59Z"},
        {"code": "GEN-2", "description": "Adventure EXP*5"},
    ]
}


def test_default_state_file_is_absolute_and_anchored():
    assert nc.default_state_file().is_absolute()
    assert nc.default_state_file().name == "known_codes.json"


def test_load_known_codes_missing_file_returns_empty(tmp_path):
    assert nc.load_known_codes(tmp_path / "nope.json") == set()


def test_load_known_codes_reads_valid_list(tmp_path):
    f = tmp_path / "known.json"
    f.write_text('["A", "B"]', encoding="utf-8")
    assert nc.load_known_codes(f) == {"A", "B"}


def test_load_known_codes_corrupt_returns_empty_and_warns(tmp_path, capsys):
    f = tmp_path / "known.json"
    f.write_text("{not json", encoding="utf-8")
    assert nc.load_known_codes(f) == set()
    assert "WARN" in capsys.readouterr().out


def test_save_known_codes_roundtrip_sorted(tmp_path):
    target = tmp_path / "state" / "known.json"
    nc.save_known_codes({"B", "A"}, target)
    assert target.read_text(encoding="utf-8").count('"A"') == 1
    assert nc.load_known_codes(target) == {"A", "B"}


def test_save_known_codes_writes_no_temp_leftover(tmp_path):
    target = tmp_path / "known.json"
    nc.save_known_codes({"X"}, target)
    assert not list(tmp_path.glob("*.tmp"))


def test_fetch_current_codes_returns_list(monkeypatch):
    monkeypatch.setattr("requests.request", lambda *a, **k: FakeResponse(payload=FAKE_GET))
    out = nc.fetch_current_codes("genshin", codes_url="https://example.test", retries=0)
    assert out == FAKE_GET["genshin"]


def test_fetch_current_codes_none_key_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "requests.request",
        lambda *a, **k: FakeResponse(payload={"genshin": None}),
    )
    assert nc.fetch_current_codes("genshin", codes_url="u", retries=0) == []


def test_fetch_current_codes_missing_key_returns_empty(monkeypatch):
    monkeypatch.setattr("requests.request", lambda *a, **k: FakeResponse(payload={}))
    assert nc.fetch_current_codes("hsr", codes_url="u", retries=0) == []


def test_fetch_current_codes_non_object_body_raises(monkeypatch):
    monkeypatch.setattr(
        "requests.request", lambda *a, **k: FakeResponse(payload=[1, 2, 3])
    )
    with pytest.raises(ValueError):
        nc.fetch_current_codes("genshin", codes_url="u", retries=0)


def test_fetch_current_codes_non_list_field_raises(monkeypatch):
    monkeypatch.setattr(
        "requests.request", lambda *a, **k: FakeResponse(payload={"genshin": "oops"})
    )
    with pytest.raises(ValueError):
        nc.fetch_current_codes("genshin", codes_url="u", retries=0)


def test_fetch_current_codes_filters_non_dict_entries(monkeypatch):
    payload = {"genshin": [{"code": "OK"}, "junk", 42]}
    monkeypatch.setattr("requests.request", lambda *a, **k: FakeResponse(payload=payload))
    out = nc.fetch_current_codes("genshin", codes_url="u", retries=0)
    assert out == [{"code": "OK"}]


def test_retry_recovers_after_transient_500(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        if len(calls) == 1:
            return FakeResponse(status=500)
        return FakeResponse(payload=FAKE_GET)

    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr("requests.request", fake_request)
    out = nc.fetch_current_codes("genshin", codes_url="https://x.test", retries=2)
    assert len(calls) == 2
    assert out == FAKE_GET["genshin"]


def test_retry_exhausts_and_reraises(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(
        "requests.request", lambda *a, **k: FakeResponse(status=503)
    )
    with pytest.raises(__import__("requests").HTTPError):
        nc.fetch_current_codes("genshin", codes_url="u", retries=2)


def test_persistent_4xx_not_retried(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(1)
        return FakeResponse(status=400)

    monkeypatch.setattr("requests.request", fake_request)
    with pytest.raises(__import__("requests").HTTPError):
        nc.fetch_current_codes("genshin", codes_url="u", retries=3)
    assert len(calls) == 1  # 4xx never retried


def test_network_error_retried_then_raised(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    seen = []

    def boom(*a, **k):
        if len(seen) < 2:
            seen.append(1)
            raise __import__("requests").ConnectionError("down")
        return FakeResponse(payload=FAKE_GET)

    monkeypatch.setattr("requests.request", boom)
    out = nc.fetch_current_codes("genshin", codes_url="u", retries=2)
    assert out == FAKE_GET["genshin"]


@pytest.mark.parametrize(
    "expiry,expected",
    [
        ("", ""),
        (None, ""),
        ("2026-12-31T23:59:59Z", ""),  # format is "còn hạn N ngày" when far
    ],
)
def test_format_expiry_badge_absent_or_far(expiry, expected):
    future = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
    code = {"expires": expiry if expiry else future}
    badge = nc.format_expiry_badge(code)
    assert ("đã hết hạn" not in badge)  # far-future shows a countdown, not expired


def test_format_expiry_badge_expired():
    code = {"expires": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}
    assert "đã hết hạn" in nc.format_expiry_badge(code)


def test_format_expiry_badge_today_shows_hours():
    code = {"expires": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()}
    assert "hết hạn sau" in nc.format_expiry_badge(code)


def test_format_expiry_badge_invalid_returns_empty():
    assert nc.format_expiry_badge({"expires": "not-a-date"}) == ""


def test_format_description_empty():
    assert nc.format_description("") == ""
    assert nc.format_description(None) == ""


def test_format_description_splits_items():
    out = nc.format_description("Mora*50000;Primogem*60")
    assert "• Mora ×50000" in out
    assert "• Primogem ×60" in out


def test_format_description_escapes_stray_star():
    out = nc.format_description("Foo*")  # name with no qty -> escape, not multiply
    assert "*" not in out or "\\*" in out


def test_send_notification_payload_shape(monkeypatch):
    captured = {}

    def fake_post(method, url, **kwargs):
        captured.update(kwargs)
        return FakeResponse(status=204)

    monkeypatch.setattr("requests.request", fake_post)
    nc.send_discord_notification("https://discord.test/webhook", FAKE_GET["genshin"], retries=0)
    body = captured["json"]
    assert body["embeds"][0]["title"] == "🎁 Genshin Impact - Giftcode mới!"
    assert "GEN-1" in body["embeds"][0]["description"]
    assert "https://genshin.hoyoverse.com/en/gift?code=GEN-1" in body["embeds"][0]["description"]


def test_send_notification_retries_transient_then_succeeds(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(status=429, retry_after="2")
        return FakeResponse(status=204)

    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr("requests.request", fake_request)
    nc.send_discord_notification("https://d.test/h", [{"code": "X"}], retries=3)
    assert len(calls) == 2


def test_send_notification_permanent_4xx_raises_runtime(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(1)
        return FakeResponse(status=404)

    monkeypatch.setattr("requests.request", fake_request)
    with pytest.raises(RuntimeError, match="Discord webhook"):
        nc.send_discord_notification("https://d.test/h", [{"code": "X"}], retries=3)
    assert len(calls) == 1


def test_main_missing_webhook_returns_1(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert nc.main(["--game", "genshin"]) == 1


def test_main_no_new_codes_returns_0(monkeypatch, tmp_path):
    state = tmp_path / "known.json"
    state.write_text('["GEN-1", "GEN-2"]', encoding="utf-8")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://d.test/h")
    monkeypatch.setattr("requests.request", lambda *a, **k: FakeResponse(payload=FAKE_GET))
    assert nc.main(["--game", "genshin", "--state", str(state)]) == 0


def test_main_dry_run_does_not_post(monkeypatch, tmp_path, capsys):
    state = tmp_path / "known.json"
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr("requests.request", lambda *a, **k: FakeResponse(payload=FAKE_GET))
    rc = nc.main(["--game", "genshin", "--state", str(state), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "GEN-1" in out


def test_main_posts_and_updates_state(monkeypatch, tmp_path):
    state = tmp_path / "known.json"
    state.write_text('[]', encoding="utf-8")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://d.test/h")

    posted = []

    def fake_request(method, url, **kwargs):
        if method == "POST":
            posted.append(kwargs.get("json"))
            return FakeResponse(status=204)
        return FakeResponse(payload=FAKE_GET)

    monkeypatch.setattr("requests.request", fake_request)
    assert nc.main(["--game", "genshin", "--state", str(state)]) == 0
    assert len(posted) == 1
    assert state.exists()
    assert nc.load_known_codes(state) == {"GEN-1", "GEN-2"}


def test_main_state_survives_across_runs_dedupe(monkeypatch, tmp_path):
    state = tmp_path / "known.json"
    state.write_text('[]', encoding="utf-8")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://d.test/h")
    posted = []

    def fake_request(method, url, **kwargs):
        if method == "POST":
            posted.append(1)
            return FakeResponse(status=204)
        return FakeResponse(payload=FAKE_GET)

    monkeypatch.setattr("requests.request", fake_request)

    # Second run: both codes now known -> nothing posted, state unchanged.
    assert nc.main(["--game", "genshin", "--state", str(state)]) == 0
    second_posted = len(posted)
    assert nc.main(["--game", "genshin", "--state", str(state)]) == 0
    assert len(posted) == second_posted  # no new post on repeat run


def test_main_fetch_error_returns_2(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://d.test/h")
    monkeypatch.setattr("requests.request", lambda *a, **k: FakeResponse(status=500))
    monkeypatch.setattr("time.sleep", lambda s: None)
    rc = nc.main(["--game", "genshin", "--state", str(tmp_path / "k.json"), "--retries", "1"])
    assert rc == 2


def test_main_uses_game_env_key(monkeypatch, tmp_path):
    state = tmp_path / "known.json"
    state.write_text('[]', encoding="utf-8")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://d.test/h")
    monkeypatch.setenv("GAME_KEY", "hsr")
    hsr_payload = {"hsr": [{"code": "SR-1", "description": "Stellar Jade*60"}]}

    def fake_request(method, url, **kwargs):
        if method == "POST":
            return FakeResponse(status=204)
        return FakeResponse(payload=hsr_payload)

    monkeypatch.setattr("requests.request", fake_request)
    assert nc.main(["--state", str(state)]) == 0
    assert nc.load_known_codes(state) == {"SR-1"}