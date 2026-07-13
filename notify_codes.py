import json
import os
import sys
from pathlib import Path

import requests

CODES_API_URL = "https://db.hashblen.com/codes"
KNOWN_CODES_FILE = Path("known_codes.json")
GAME_KEY = "genshin"  # đổi thành "hsr" hoặc "zzz" nếu muốn dùng lại cho game khác


def load_known_codes() -> set[str]:
    """Đọc danh sách code đã thông báo trước đó từ file JSON local."""
    if not KNOWN_CODES_FILE.exists():
        return set()
    try:
        with open(KNOWN_CODES_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] Không đọc được {KNOWN_CODES_FILE}: {e}. Coi như chưa có code nào.")
        return set()


def save_known_codes(codes: set[str]) -> None:
    """Ghi lại danh sách code đã biết để lần chạy sau so sánh."""
    with open(KNOWN_CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(codes), f, ensure_ascii=False, indent=2)


def fetch_current_codes() -> list[dict]:
    """Gọi API Hoyocodes, trả về list code hiện tại của Genshin."""
    resp = requests.get(CODES_API_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get(GAME_KEY, [])


def send_discord_notification(webhook_url: str, new_codes: list[dict]) -> None:
    """Gửi embed message vào Discord webhook cho các code mới."""
    lines = []
    for c in new_codes:
        code = c.get("code", "???")
        desc = c.get("description", "").strip()
        redeem_url = f"https://genshin.hoyoverse.com/en/gift?code={code}"
        line = f"**`{code}`** — {desc}\n[Redeem]({redeem_url})" if desc else f"**`{code}`**\n[Redeem]({redeem_url})"
        lines.append(line)

    payload = {
        "embeds": [
            {
                "title": "🎁 Genshin Impact - Giftcode mới!",
                "description": "\n\n".join(lines),
                "color": 0x1E90FF,
            }
        ]
    }

    resp = requests.post(webhook_url, json=payload, timeout=15)
    resp.raise_for_status()


def main() -> int:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[ERROR] Thiếu biến môi trường DISCORD_WEBHOOK_URL", file=sys.stderr)
        return 1

    known_codes = load_known_codes()
    current_codes = fetch_current_codes()

    new_codes = [c for c in current_codes if c.get("code") not in known_codes]

    if not new_codes:
        print("Không có code mới.")
        return 0

    print(f"Tìm thấy {len(new_codes)} code mới: {[c.get('code') for c in new_codes]}")
    send_discord_notification(webhook_url, new_codes)

    all_codes = known_codes | {c.get("code") for c in current_codes if c.get("code")}
    save_known_codes(all_codes)
    print("Đã gửi thông báo và cập nhật known_codes.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
