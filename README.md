# 🎁 Genshin Giftcode Notifier

Bot tự động kiểm tra giftcode Genshin Impact mới và gửi thông báo vào Discord — chạy hoàn toàn miễn phí bằng GitHub Actions, không cần server riêng.

## Cách hoạt động

```
GitHub Actions (cron mỗi giờ)
  → fetch giftcode từ Hoyocodes API
  → so sánh với danh sách code đã biết
  → có code mới? → gửi embed message vào Discord qua Webhook
  → cập nhật lại danh sách code đã biết
```

- **Nguồn dữ liệu**: [Hoyocodes API](https://github.com/heartlog/Hoyocodes) (`db.hashblen.com/codes`) — JSON public, tự động cập nhật, không cần đăng nhập.
- **Không spam**: mỗi code chỉ được thông báo 1 lần nhờ file `known_codes.json` lưu trạng thái, tự commit lại vào repo sau mỗi lần chạy.
- **Chi phí**: $0 — chạy trên GitHub Actions free tier (24 lần/ngày, mỗi lần vài chục giây).

## Cấu trúc

```
.
├── notify_codes.py              # fetch + so sánh + gửi Discord
├── known_codes.json             # state: danh sách code đã thông báo
├── requirements.txt
└── .github/workflows/notify.yml # cron trigger (mỗi giờ) + chạy tay
```

## Cài đặt

1. Fork/clone repo này
2. Tạo Discord Webhook: **Server Settings → Integrations → Webhooks → New Webhook** → copy URL
3. Vào **Settings → Secrets and variables → Actions** của repo, thêm secret:
   - Name: `DISCORD_WEBHOOK_URL`
   - Value: URL webhook vừa tạo
4. Vào tab **Actions**, chọn workflow **Genshin Giftcode Notifier** → **Run workflow** để test tay

Workflow sẽ tự động chạy mỗi giờ sau đó, không cần làm gì thêm.

## Cấu hình thêm

- Đổi giờ chạy: sửa dòng `cron` trong `.github/workflows/notify.yml` ([cron syntax](https://crontab.guru/))
- Dùng cho game khác (Honkai: Star Rail, Zenless Zone Zero): đổi `GAME_KEY` trong `notify_codes.py` thành `"hsr"` hoặc `"zzz"`

## Giới hạn

- Phụ thuộc vào Hoyocodes API còn hoạt động; nếu API sập lâu dài cần đổi nguồn khác (Game8, Prydwen...)
- Không có xử lý retry nếu Discord webhook tạm thời lỗi (sẽ thử lại ở lần chạy cron kế tiếp)
