# Koyeb Deployment Guide

## Tại sao Koyeb?

| Tiêu chí | Koyeb Free Tier |
|----------|----------------|
| Giá | Miễn phí mãi mãi (1 nano service) |
| RAM | 512 MB |
| Always-on | ✅ Không sleep (khác Render) |
| HTTPS | ✅ Tự động, URL cố định |
| Cold start | ❌ Không có |
| Deploy từ | GitHub repo (auto-deploy khi push) |

---

## Yêu cầu trước khi deploy

- [ ] Code đã push lên GitHub (repo public hoặc private đều được)
- [ ] Có đầy đủ 5 biến môi trường (xem `.env.example`)
- [ ] Bot Telegram đã được tạo qua @BotFather
- [ ] ORS API key đã lấy từ openrouteservice.org

---

## Bước 1 — Tạo tài khoản Koyeb

1. Truy cập [app.koyeb.com](https://app.koyeb.com) → **Sign up** (dùng GitHub cho tiện)
2. Xác nhận email

---

## Bước 2 — Tạo Service mới

1. Dashboard → **Create Service**
2. Chọn **GitHub** → Authorize Koyeb truy cập repo của bạn
3. Chọn repo `transit-sleep-agent`
4. Koyeb tự phát hiện `Dockerfile` → **Builder: Dockerfile** ✅

### Cấu hình service:

| Trường | Giá trị |
|--------|---------|
| Service name | `transit-sleep-agent` (hoặc tên tùy ý) |
| Region | `fra` (Frankfurt) hoặc `was` (Washington) — chọn gần VN |
| Instance type | **Nano** (free) |
| Port | `8000` |

---

## Bước 3 — Lấy URL Koyeb trước khi điền env vars

Trước khi deploy, Koyeb hiển thị URL dạng:
```
https://<service-name>-<hash>.koyeb.app
```

Ví dụ: `https://transit-sleep-agent-abc123.koyeb.app`

Ghi lại URL này, dùng cho bước tiếp theo.

---

## Bước 4 — Điền Environment Variables

Trong phần **Environment variables** của Koyeb service, thêm đủ 5 biến:

| Key | Value |
|-----|-------|
| `TELEGRAM_BOT_TOKEN` | Token từ @BotFather |
| `ORS_API_KEY` | Key từ openrouteservice.org |
| `BACKEND_URL` | `https://<service-name>-<hash>.koyeb.app` |
| `MINI_APP_URL` | `https://<service-name>-<hash>.koyeb.app/miniapp` |
| `OWNER_CHAT_ID` | Chat ID Telegram của bạn |

> ⚠️ **Quan trọng**: `BACKEND_URL` và `MINI_APP_URL` phải dùng đúng URL Koyeb, không phải ngrok.

---

## Bước 5 — Deploy

1. Nhấn **Deploy** → Koyeb bắt đầu build Docker image
2. Quá trình build ~2-3 phút
3. Khi status chuyển sang **Healthy** ✅ → app đang chạy

### Kiểm tra:
```
GET https://<service-name>-<hash>.koyeb.app/health
```
Response mong đợi:
```json
{"status": "ok", "bot_username": "your_bot_name"}
```

### Xác nhận webhook đã đăng ký:
Trong Koyeb logs lúc startup phải thấy:
```
INFO  backend.main: Webhook registered: https://<...>.koyeb.app/telegram/webhook
```

---

## Bước 6 — Cấu hình Telegram Mini App URL

Để Telegram cho phép mở Mini App từ URL của bạn, cần đăng ký với @BotFather:

1. Mở Telegram → @BotFather
2. Gửi `/mybots` → chọn bot của bạn
3. **Bot Settings** → **Menu Button** → **Configure menu button**
4. Nhập URL: `https://<service-name>-<hash>.koyeb.app/miniapp`

> Bước này cần thiết để `WebAppInfo` URL hợp lệ với Telegram.

---

## Auto-deploy khi push code

Koyeb tự động redeploy mỗi khi bạn push lên branch `main`:

```
git push origin main  →  Koyeb build + deploy tự động (~2-3 phút)
```

---

## Xem logs

Dashboard → Service → **Logs** tab

Các log quan trọng cần thấy khi startup:
```
INFO  backend.main: Starting Telegram bot polling...
INFO  backend.main: Bot is polling. Send /start to your bot on Telegram.
INFO  backend.scheduler: Scheduler started — polling every 30s
```

---

## So sánh môi trường

| | Local (dev) | Koyeb (production) |
|--|-------------|-------------------|
| Start command | `uvicorn ... --reload --port 8001` | `uvicorn ... --host 0.0.0.0 --port 8000` |
| HTTPS | ngrok tunnel | Koyeb automatic |
| URL thay đổi? | ✅ Mỗi lần restart ngrok | ❌ Cố định |
| `--reload` | ✅ (hot reload khi dev) | ❌ (không cần trong production) |
| Session persistence | RAM (mất khi restart) | RAM (mất khi redeploy) |

---

## Troubleshooting

### Lỗi 409 Conflict trong logs
App đã chuyển sang **webhook mode** — lỗi này không còn xảy ra.
Nguyên nhân cũ: hai instance cùng polling. Webhook mode loại bỏ hoàn toàn vấn đề này.

### Bot không nhận được tin nhắn
- Kiểm tra logs startup: phải có dòng `Webhook registered: https://...`
- Kiểm tra `BACKEND_URL` đúng URL Koyeb chưa (không có dấu `/` ở cuối)
- Kiểm tra `TELEGRAM_BOT_TOKEN` đúng chưa

### Mini App không mở được
- Kiểm tra `MINI_APP_URL` đúng URL Koyeb chưa
- URL phải là HTTPS
- Đã cấu hình Menu Button trong @BotFather chưa?

### `/health` trả về 502 hoặc không kết nối được
- Service chưa Healthy — đợi build xong
- Xem Build logs tìm lỗi

### Redeploy mà session bị mất
- Đây là behavior bình thường ở M1/M2 (in-memory session)
- User chỉ cần gửi `/start` lại sau khi redeploy
