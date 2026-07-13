# 🎁 Genshin Giftcode Notifier

Bot tự động kiểm tra giftcode Genshin Impact mới và gửi thông báo vào Discord — chạy hoàn toàn miễn phí bằng GitHub Actions, không cần server riêng.

## Cách hoạt động

```
cron-job.org (mỗi giờ, đúng giờ tuyệt đối)
  → POST tới GitHub API để trigger workflow_dispatch
  → GitHub Actions chạy: fetch giftcode từ Hoyocodes API
  → so sánh với danh sách code đã biết
  → có code mới? → gửi embed message vào Discord qua Webhook
  → cập nhật lại danh sách code đã biết
```

- **Nguồn dữ liệu**: [Hoyocodes API](https://github.com/heartlog/Hoyocodes) (`db.hashblen.com/codes`) — JSON public, tự động cập nhật, không cần đăng nhập.
- **Không spam**: mỗi code chỉ được thông báo 1 lần nhờ file `known_codes.json` lưu trạng thái, tự commit lại vào repo sau mỗi lần chạy.
- **Trigger bằng cron-job.org**, không dùng `schedule:` nội bộ của GitHub Actions — GitHub hay throttle/bỏ qua scheduled run vào giờ cao điểm (đặc biệt phút `:00`), gọi API trực tiếp từ bên ngoài chính xác và đáng tin cậy hơn.
- **Chi phí**: $0 — GitHub Actions free tier (~24 lần/ngày, mỗi lần vài chục giây) + cron-job.org free.

## Cấu trúc

```
.
├── notify_codes.py              # fetch + so sánh + gửi Discord
├── known_codes.json             # state: danh sách code đã thông báo
├── requirements.txt
└── .github/workflows/notify.yml # workflow_dispatch, trigger từ cron-job.org
```

## Cài đặt

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

## Cấu hình thêm

- Đổi tần suất chạy: sửa lịch trực tiếp trên cron-job.org, không cần đụng vào code/yml
- Dùng cho game khác (Honkai: Star Rail, Zenless Zone Zero): đổi `GAME_KEY` trong `notify_codes.py` thành `"hsr"` hoặc `"zzz"`

## Giới hạn

- Phụ thuộc vào Hoyocodes API còn hoạt động; nếu API sập lâu dài cần đổi nguồn khác (Game8, Prydwen...)
- Không có xử lý retry nếu Discord webhook tạm thời lỗi (sẽ thử lại ở lần chạy cron kế tiếp)
