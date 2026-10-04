"""Genshin/HoYo giftcode → Discord notifier.

Fetches current redeemable gift codes from the public Hoyocodes API
(https://db.hashblen.com/codes), diffs them against a local state file of
already-notified codes, and posts only the new ones to a Discord webhook as a
single embed. Designed to run from cron / GitHub Actions (workflow_dispatch)
for any HoYo game that the API exposes a key for ("genshin", "hsr", "zzz").
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CONTACT_HEADER = {
    "User-Agent": "discord-giftcode-notifier (+python-requests)"
}

# Public, no-auth, no-login JSON endpoint of the heartlog/Hoyocodes project.
CODES_API_URL = "https://db.hashblen.com/codes"
DEFAULT_GAME_KEY = "genshin"
DEFAULT_RETRIES = 3
RETRY_ON_STATUS = {429, 500, 502, 503, 504}


def default_state_file() -> Path:
    """Anchor known-codes state to this script's directory.

    A bare relative path (the old behaviour) resolves against the process CWD,
    so the notifier silently forgot / re-notified every code when launched from
    anywhere other than the repo root (exactly where a cron job lives). Binding
    to the script location makes state tracking location-independent.
    """
    return Path(__file__).resolve().parent / "known_codes.json"


def load_known_codes(state_file: Path) -> set[str]:
    """Read the set of already-notified codes from the local JSON state file."""
    if not state_file.exists():
        return set()
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError, TypeError) as e:
        print(f"[WARN] Không đọc được {state_file}: {e}. Coi như chưa có code nào.")
        return set()


def save_known_codes(codes: set[str], state_file: Path) -> None:
    """Write the known set back to the state file, atomically via temp+rename.

    A crash mid-write otherwise leaves a truncated file whose next parse is
    swallowed by load_known_codes' error path — losing the whole dedupe set.
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(codes), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(state_file)


def _request_with_retry(
    method: str,
    url: str,
    *,
    retries: int,
    **kwargs: Any,
) -> requests.Response:
    """Perform an HTTP request with exponential backoff on transient failures.

    Retries on connection errors and the 429/5xx statuses, honouring a
    Retry-After delay when the server provides one. Any other status (or a
    permanent 4xx) raises immediately. Mirrors the roadmap's "retry when the
    Discord webhook temporarily errors" item for both fetch and post.
    """
    for attempt in range(retries + 1):
        try:
            resp = requests.request(method, url, timeout=15, **kwargs)
        except requests.RequestException:
            if attempt == retries:
                raise
            # Network blip on a bare `raise_for_status` path would otherwise
            # abort an entire run over a transient connection drop.
            time.sleep(_backoff(attempt, None))
            continue

        if resp.status_code in RETRY_ON_STATUS and attempt < retries:
            time.sleep(_backoff(attempt, resp.headers.get("Retry-After")))
            continue
        resp.raise_for_status()
        return resp

    raise RuntimeError("unreachable")


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after and retry_after.isdigit():
        return int(retry_after)
    return min(2 ** attempt, 8) * (0.5 + 0.5)  # 1, 2, 4 ... capped at 8s


def fetch_current_codes(game_key: str, *, codes_url: str, retries: int) -> list[dict]:
    """Call the Hoyocodes API and return the current code list for `game_key`.

    Defensively handles a response body that is not the expected mapping
    (list/None) or missing the game key, so a partial API outage degrades to an
    explicit error rather than a confusing AttributeError deep in the caller.
    """
    resp = _request_with_retry(
        "GET", codes_url, retries=retries, headers=CONTACT_HEADER
    )
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"API response is {type(data).__name__}, expected a JSON object")
    codes = data.get(game_key, [])
    if codes is None:
        return []
    if not isinstance(codes, list):
        raise ValueError(f"API field '{game_key}' is {type(codes).__name__}, expected a list")
    return [c for c in codes if isinstance(c, dict)]


def format_expiry_badge(code: dict) -> str:
    """Return a short validity badge from the code's expiry, or "" if absent."""
    expiry_raw = code.get("expires") or code.get("expiry") or code.get("expiration")
    if not expiry_raw:
        return ""
    try:
        expiry_dt = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        total_hours = (expiry_dt - now).total_seconds() / 3600
        if total_hours < 0:
            return " · ⚠ đã hết hạn"
        if total_hours < 24:
            days = int(total_hours // 24)
            hours = int(total_hours % 24)
            if days == 0:
                return f" · ⚠ hết hạn sau {max(hours, 1)}h"
            return f" · ⚠ hết hạn sau {days} ngày {hours}h"
        return f" · còn hạn {int(total_hours // 24)} ngày"
    except (ValueError, TypeError):
        return ""


def format_description(desc: str | None) -> str:
    """Reformat raw 'Item*Qty;Item*Qty;...' rewards into bullet lines.

    Escapes stray '*' so Discord cannot interpret a reward name as emphasis.
    Accepts None defensively (API data is untrusted).
    """
    if not desc:
        return ""
    items = [item.strip() for item in desc.split(";") if item.strip()]
    formatted = []
    for item in items:
        name, sep, qty = item.rpartition("*")
        if sep and qty.strip().lstrip("x").isdigit():
            formatted.append(f"• {name.strip()} ×{qty.strip()}")
        else:
            # not "name*qty" as expected -> escape '*' so markdown doesn't break
            formatted.append(f"• {item.replace('*', chr(92) + '*')}")
    return "\n".join(formatted)


def send_discord_notification(
    webhook_url: str, new_codes: list[dict], *, retries: int
) -> None:
    """Send a single embed to the Discord webhook describing the new codes."""
    lines = []
    for c in new_codes:
        code = c.get("code", "???")
        desc = format_description(c.get("description", "").strip())
        redeem_url = f"https://genshin.hoyoverse.com/en/gift?code={code}"
        badge = format_expiry_badge(c)
        header = f"**`{code}`**{badge}"
        line = f"{header}\n{desc}\n[Redeem]({redeem_url})" if desc else (
            f"{header}\n[Redeem]({redeem_url})"
        )
        lines.append(line)

    checked_at = datetime.now(timezone.utc).strftime("%H:%M UTC")

    embed = {
        "title": "🎁 Genshin Impact - Giftcode mới!",
        "description": "\n\n".join(lines),
        "color": 0x1E90FF,
        "footer": {"text": f"Check tự động mỗi giờ · Nguồn: Hoyocodes · Kiểm tra lúc {checked_at}"},
    }
    if THUMBNAIL_URL:
        embed["thumbnail"] = {"url": THUMBNAIL_URL}

    payload = {"embeds": [embed]}
    try:
        _request_with_retry(
            "POST", webhook_url, retries=retries, json=payload, headers=CONTACT_HEADER
        )
    except requests.HTTPError as e:
        # A 4xx from Discord is a permanent config error (bad URL, deleted
        # webhook) — never worth retrying; surface it loudly.
        raise RuntimeError(f"Discord webhook rejected the payload: {e}") from e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch new HoYo gift codes and post them to a Discord webhook."
    )
    parser.add_argument(
        "--game",
        default=os.environ.get("GAME_KEY", DEFAULT_GAME_KEY),
        help="API key for the target game: genshin (default), hsr, zzz, ...",
    )
    parser.add_argument(
        "--codes-url",
        default=CODES_API_URL,
        help="Hoyocodes API base URL (default: %(default)s).",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=default_state_file(),
        help="Path to the known-codes state file (default: next to this script).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Retry attempts for transient HTTP failures (default: %(default)s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print what would be sent, without posting to Discord.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url and not args.dry_run:
        print("[ERROR] Thiếu biến môi trường DISCORD_WEBHOOK_URL", file=sys.stderr)
        return 1

    try:
        current_codes = fetch_current_codes(
            args.game, codes_url=args.codes_url, retries=args.retries
        )
    except (requests.RequestException, ValueError) as e:
        print(f"[ERROR] Không lấy được danh sách code: {e}", file=sys.stderr)
        return 2

    known_codes = load_known_codes(args.state)
    new_codes = [c for c in current_codes if c.get("code") not in known_codes]

    if not new_codes:
        print("Không có code mới.")
        return 0

    print(f"Tìm thấy {len(new_codes)} code mới: {[c.get('code') for c in new_codes]}")

    if args.dry_run:
        print("[DRY-RUN] Sẽ gửi thông báo nhưng không POST tới Discord:")
        print("[DRY-RUN] " + json.dumps(
            {
                "game": args.game,
                "new_codes": [c.get("code") for c in new_codes],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    assert webhook_url is not None  # guaranteed by the empty-check above
    send_discord_notification(webhook_url, new_codes, retries=args.retries)

    all_codes = known_codes | {
        str(c.get("code")) for c in current_codes if c.get("code")
    }
    save_known_codes(all_codes, args.state)
    print("Đã gửi thông báo và cập nhật known_codes.json")
    return 0


THUMBNAIL_URL = (
    "https://raw.githubusercontent.com/tuananh511/"
    "discordXgenshin-giftcode-notifier/main/assets/icon.png"
)


if __name__ == "__main__":
    sys.exit(main())