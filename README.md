# 🎁 Genshin Giftcode Notifier

> Tự động phát hiện và gửi giftcode Genshin Impact mới vào Discord mỗi giờ.

![Release](https://img.shields.io/github/v/release/tuananh511/discordXgenshin-giftcode-notifier?style=flat-square)
![License](https://img.shields.io/github/license/tuananh511/discordXgenshin-giftcode-notifier?style=flat-square)
![Build](https://img.shields.io/github/actions/workflow/status/tuananh511/discordXgenshin-giftcode-notifier/notify.yml?style=flat-square)

## Overview

Bot tự động kiểm tra giftcode Genshin Impact mới và gửi thông báo vào Discord — chạy hoàn toàn miễn phí bằng GitHub Actions, không cần server riêng.

Luồng hoạt động:

```
cron-job.org (mỗi giờ, đúng giờ tuyệt đối)
  → POST tới GitHub API để trigger workflow_dispatch
  → GitHub Actions chạy: fetch giftcode từ Hoyocodes API
  → so sánh với danh sách code đã biết
  → có code mới? → gửi embed message vào Discord qua Webhook
  → cập nhật lại danh sách code đã biết
```

## Features

- Tự động fetch giftcode mới nhất từ [Hoyocodes API](https://github.com/heartlog/Hoyocodes) (`db.hashblen.com/codes`) — JSON public, không cần đăng nhập
- Gửi embed message đẹp mắt vào Discord qua Webhook ngay khi phát hiện code mới
- Không spam: mỗi code chỉ thông báo 1 lần nhờ `known_codes.json` lưu trạng thái, tự commit lại vào repo sau mỗi lần chạy
- Trigger bằng cron-job.org thay vì `schedule:` nội bộ của GitHub Actions, tránh bị throttle/bỏ qua vào giờ cao điểm
- Chi phí $0: GitHub Actions free tier (~24 lần/ngày) + cron-job.org free
- Dễ đổi sang game khác cùng hệ (Honkai: Star Rail, Zenless Zone Zero) chỉ bằng 1 dòng cấu hình

## Installation

1. Fork/clone repo này
2. Tạo Discord Webhook: **Server Settings → Integrations → Webhooks → New Webhook** → copy URL
3. Vào **Settings → Secrets and variables → Actions** của repo, thêm secret:
   - Name: `DISCORD_WEBHOOK_URL`
   - Value: URL webhook vừa tạo
4. Tạo GitHub Personal Access Token (classic, scope `repo` + `workflow`) tại `github.com/settings/tokens`
5. Tạo cronjob trên [cron-job.org](https://cron-job.org):
   - URL: `https://api.github.com/repos/<user>/<repo>/actions/workflows/notify.yml/dispatches`
   - Method: `POST`
   - Headers: `Authorization: Bearer <PAT>`, `Accept: application/vnd.github+json`
   - Body (JSON): `{"ref":"main"}`
   - Lịch: mỗi giờ (không cần né phút nào)
6. Bấm "Run now" trên cron-job.org để test, kiểm tra tab **Actions** trên GitHub có run mới xuất hiện không

## Usage

- **Đổi tần suất chạy**: sửa lịch trực tiếp trên cron-job.org, không cần đụng vào code/yml
- **Dùng cho game khác**: truyền `--game hsr` (Honkai: Star Rail) hoặc `--game zzz` (Zenless
  Zone Zero), hoặc đặt biến môi trường `GAME_KEY`. Không cần sửa code nữa.
- **Cấu trúc repo**:
  ```
  .
  ├── notify_codes.py              # fetch + so sánh + gửi Discord
  ├── known_codes.json             # state: danh sách code đã thông báo
  ├── pyproject.toml               # packaging + pytest/ruff config
  ├── tests/                       # 35 offline tests (không cần API/Discord)
  ├── requirements.txt
  └── .github/workflows/notify.yml # workflow_dispatch, trigger từ cron-job.org
  ```

### CLI

`python notify_codes.py` vẫn hoạt động y hệt như trước (không tham số). Thêm các flag mới:

| Flag | Ý nghĩa |
|---|---|
| `--game KEY` | Chọn game: `genshin` (mặc định), `hsr`, `zzz`, ... Hoặc dùng env `GAME_KEY` |
| `--codes-url URL` | Đổi nguồn API Hoyocodes (mặc định: `https://db.hashblen.com/codes`) |
| `--state PATH` | Đổi đường dẫn file state `known_codes.json` (mặc định: ngay cạnh script) |
| `--retries N` | Số lần retry cho lỗi mạng tạm thời / Discord 429-5xx (mặc định: 3) |
| `--dry-run` | Chỉ in ra code mới, **không POST** tới Discord (hữu ích để thử trước) |

Ví dụ chạy thử không gửi:
```bash
DISCORD_WEBHOOK_URL=x python notify_codes.py --dry-run
```

### Retry tự động

Kể từ v1.1, mọi lệnh gọi HTTP (fetch API lẫn POST Discord) đều có retry với backoff theo
exponential khi gặp lỗi thoáng qua (mất kết nối, HTTP 429/500/502/503/504), tôn trọng header
`Retry-After` của Discord. Điều này hiện thực hoá mục đầu tiên trong Roadmap.

### Chạy test

```bash
uv sync --extra dev        # hoặc: uv pip install -r requirements.txt pytest ruff
uv run pytest              # 35 tests, không cần network và không cần key
uv run ruff check notify_codes.py tests/
```

## Roadmap

- [x] Cơ chế retry khi Discord webhook lỗi tạm thời
- [x] Chọn game qua CLI/env (`--game` / `GAME_KEY`) thay vì sửa source
- [ ] Hỗ trợ nguồn dữ liệu dự phòng (Game8, Prydwen...) khi Hoyocodes API sập
- [ ] Hỗ trợ gửi thông báo song song cho nhiều game cùng lúc

## License

MIT
