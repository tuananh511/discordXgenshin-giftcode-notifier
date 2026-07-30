import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

CODES_API_URL = "https://db.hashblen.com/codes"
KNOWN_CODES_FILE = Path("known_codes.json")
GAME_KEY = "genshin"  # đổi thành "hsr" hoặc "zzz" nếu muốn dùng lại cho game khác

# Icon dùng làm thumbnail cho embed. Logo chính thức Genshin không có bản free-license
# ổn định để nhúng link trực tiếp (dễ bị xóa/404 như link Wikimedia cũ). Khuyên dùng:
# tự upload 1 ảnh icon vào repo (vd: assets/icon.png) rồi trỏ tới link raw GitHub, ví dụ:
# https://raw.githubusercontent.com/<user>/<repo>/main/assets/icon.png
THUMBNAIL_URL = "https://raw.githubusercontent.com/tuananh511/discordXgenshin-giftcode-notifier/main/assets/icon.png"


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


def format_expiry_badge(code: dict) -> str:
    """Trả về badge hạn dùng nếu API có field expires/expiry, không có thì bỏ qua."""
    expiry_raw = code.get("expires") or code.get("expiry") or code.get("expiration")
    if not expiry_raw:
        return ""
    try:
        expiry_dt = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
        days_left = (expiry_dt - datetime.now(timezone.utc)).days
        if days_left < 0:
            return " · ⚠ đã hết hạn"
        if days_left == 0:
            return " · ⚠ hết hạn hôm nay"
        return f" · còn hạn {days_left} ngày"
    except (ValueError, TypeError):
        return ""


def format_description(desc: str) -> str:
    """Định dạng lại description thô từ API (dạng 'Item*Qty;Item*Qty;...')
    thành danh sách gạch đầu dòng, tránh dấu * bị Discord hiểu nhầm thành in nghiêng."""
    if not desc:
        return ""
    items = [item.strip() for item in desc.split(";") if item.strip()]
    formatted = []
    for item in items:
        name, sep, qty = item.rpartition("*")
        if sep and qty.strip().lstrip("x").isdigit():
            formatted.append(f"• {name.strip()} ×{qty.strip()}")
        else:
            # không đúng định dạng "tên*số lượng" như kỳ vọng -> escape dấu * để không vỡ markdown
            formatted.append(f"• {item.replace('*', chr(92) + '*')}")
    return "\n".join(formatted)


def send_discord_notification(webhook_url: str, new_codes: list[dict]) -> None:
    """Gửi embed message vào Discord webhook cho các code mới."""
    lines = []
    for c in new_codes:
        code = c.get("code", "???")
        desc = format_description(c.get("description", "").strip())
        redeem_url = f"https://genshin.hoyoverse.com/en/gift?code={code}"
        badge = format_expiry_badge(c)
        header = f"**`{code}`**{badge}"
        line = f"{header}\n{desc}\n[Redeem]({redeem_url})" if desc else f"{header}\n[Redeem]({redeem_url})"
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
