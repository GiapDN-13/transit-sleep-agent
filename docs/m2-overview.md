# Milestone 2 — Stability

## Mục tiêu

Biến MVP (M1) thành một hệ thống **đủ tin cậy để dùng thực tế**:
không false alarm, không bỏ lỡ trạm, đánh thức được người dùng dù màn hình tắt hay điện thoại để im lặng.

---

## Các cải tiến so với M1

| Hạng mục | M1 (trước) | M2 (sau) |
|---|---|---|
| State machine | Thiếu trạng thái IDLE | IDLE → ACTIVE → WAKING rõ ràng |
| Poll interval | Cố định | Động theo ETA band |
| ETA | Raw ORS trực tiếp | Smoothed bằng median window |
| Wake alert | Gửi một lần | Retry tối đa 3 lần với leo thang |
| Thông báo cuối | Telegram message | Telegram + ntfy alarm (20 ping) |
| Deploy | Local + polling | Koyeb + webhook |
| Logging | Không có | Trip history JSONL |

---

## State Machine

```
          /start + chọn điểm + prep time
                     │
                     ▼
               ┌──────────┐
               │   IDLE   │  ← Session tạo xong, chờ GPS từ Mini App
               └────┬─────┘
                    │  POST /trips/start (GPS đầu tiên)
                    ▼
               ┌──────────┐
               │  ACTIVE  │  ← Scheduler đang poll ETA mỗi tick
               └────┬─────┘
                    │  smoothed ETA ≤ prep_time
                    ▼
               ┌──────────┐
               │  WAKING  │  ← Wake alert gửi, chờ user ack
               └────┬─────┘
          ┌─────────┼──────────┐
          │         │          │
      wake_ack  wake_snooze  wake_stop
          │         │          │
       clear     ACTIVE      clear
       session  (5 phút)    session
```

**Ghi chú:**
- `DONE` được định nghĩa trong enum nhưng không dùng — session được `clear()` thay vì set DONE
- Retry trong `WAKING`: nếu sau `WAKE_RETRY_AFTER` (3 phút) user chưa ack → tăng `wake_retry_count` và gửi lại, tối đa `WAKE_MAX_RETRIES` (3) lần

---

## Polling Strategy theo ETA Bands

Scheduler không poll với interval cố định mà điều chỉnh theo ETA hiện tại:

```
ETA > 30 phút   →  poll mỗi 5 phút   (tiết kiệm ORS quota)
ETA 10–30 phút  →  poll mỗi 2 phút
ETA < 10 phút   →  poll mỗi 30 giây  (theo dõi sát)
Chưa có GPS     →  poll mỗi 1 phút
```

**Tại sao:** ORS free tier có giới hạn 2000 req/ngày. Nếu poll 30 giây cả hành trình 2 tiếng = 240 req. Poll động còn ~50 req cho cùng hành trình đó.

---

## ETA Smoothing

**Vấn đề:** GPS noise khiến ETA nhảy loạn → false alarm (báo thức khi còn xa).

**Giải pháp:** Dùng **median của sliding window** 3 lần đo gần nhất.

```python
ETA_WINDOW_SIZE = 3

session.eta_window.append(raw_eta)       # thêm đo mới
if len(session.eta_window) > ETA_WINDOW_SIZE:
    session.eta_window.pop(0)            # xoá đo cũ nhất

smoothed_eta = statistics.median(session.eta_window)
```

**Hiệu quả:**
- Cần ít nhất ⌈3/2⌉ = 2 lần đo liên tiếp dưới ngưỡng mới trigger alert
- Một lần GPS nhiễu không đủ gây false alarm
- Tradeoff: phát hiện chậm hơn tối đa 1 poll interval (~30 giây)

---

## Wake Alert Retry & Escalation

Nếu user không phản hồi sau 3 phút, scheduler retry với cường độ tăng dần:

### Retry #0 — Cảnh báo lần đầu
- Telegram: 1 tin alert + nút hành động
- ntfy: priority `high` (1 notification, có âm thanh)

### Retry #1 — Nhắc lại
- Telegram: 1 tin alert + spam 3 tin ⏰ (cách nhau 1 giây)
- ntfy: priority `urgent` (bypass DND)

### Retry #2+ — Khẩn cấp
- Telegram: 1 tin alert + spam 5 tin 🚨 (cách nhau 0.5 giây) + voice TTS tiếng Việt
- ntfy: priority `max` — **20 ping cách nhau 0.5 giây** → ~10 giây kêu như báo thức

Sau `WAKE_MAX_RETRIES` (3) lần → dừng retry (tránh spam vô tận).

---

## ntfy.sh — Alarm Bypass Silent Mode

**Vấn đề:** Telegram voice message không tự phát khi màn hình tắt.

**Giải pháp:** Tích hợp [ntfy.sh](https://ntfy.sh) — push notification miễn phí, có thể bypass chế độ im lặng và DND trên Android.

### Cách hoạt động

```
Backend (Koyeb)
    │
    │  POST https://ntfy.sh/{NTFY_TOPIC}
    │  Headers: Priority=max, Tags=alarm_clock,...
    │
    ▼
ntfy.sh server
    │
    │  push
    ▼
ntfy app (điện thoại)
    → phát âm thanh báo thức
    → hiện full-screen notification
    → kêu cho đến khi bấm tắt
```

### Setup (2 bước)
1. Cài app **ntfy** (Android/iOS, miễn phí) → Subscribe topic `transit-sleep-agent`
2. Koyeb → Environment Variables → `NTFY_TOPIC=transit-sleep-agent`

### Config trong app ntfy (quan trọng)
Giữ subscription → Settings:
- **Notification sound**: chọn tiếng báo thức (Alarm, Platinum...)
- **Override Do Not Disturb**: bật ✅
- **Min. priority**: Any

### Behavior theo retry

| Retry | ntfy Priority | Hành vi |
|-------|--------------|---------|
| 0 | `high` | 1 notification, có âm thanh |
| 1 | `urgent` | 1 notification, bypass DND |
| ≥2 | `max` | **20 ping × 0.5s** — loop như báo thức ~10 giây |

---

## Logging / Trip History

Mỗi hành trình kết thúc (ack/stop/timeout) được ghi vào `trip_history.jsonl`:

```json
{"destination": "Bến Thành", "started_at": "2025-01-01T08:00:00", "outcome": "acked", "duration_min": 45, "wake_retries": 1}
```

File JSONL — mỗi dòng là một JSON object, dễ query bằng `jq` hoặc pandas.

---

## Deploy — Koyeb + Webhook

### Tại sao Webhook thay vì Polling?

Polling (M1): bot liên tục gọi Telegram API `getUpdates` → conflict khi chạy 2 instance (local + Koyeb).

Webhook (M2): Telegram chủ động POST update vào `/telegram/webhook` → không conflict, không cần long-polling.

### Luồng webhook

```
Telegram server
    │  POST /telegram/webhook  (mỗi khi có message/callback)
    ▼
Koyeb (FastAPI)  ←── routes.py: @router.post("/telegram/webhook")
    │
    ▼
bot_app.process_update(update)
    │
    ▼
handlers trong bot.py
```

### Environment Variables (Koyeb)

| Key | Ví dụ | Mô tả |
|-----|-------|-------|
| `TELEGRAM_BOT_TOKEN` | `7xxx:AAx...` | Token từ @BotFather |
| `ORS_API_KEY` | `eyJvcm...` | openrouteservice.org |
| `BACKEND_URL` | `https://xxx.koyeb.app` | URL public của Koyeb app |
| `MINI_APP_URL` | `https://xxx.koyeb.app/miniapp` | URL Mini App |
| `OWNER_CHAT_ID` | `123456789` | Chat ID từ @userinfobot |
| `NTFY_TOPIC` | `transit-sleep-agent` | Topic ntfy (tuỳ chọn) |

---

## Bot Commands

| Lệnh | Mô tả |
|------|-------|
| `/start` | Bắt đầu hành trình — chọn điểm xuống |
| `/help` | Hướng dẫn sử dụng |
| `/status` | Xem trạng thái hành trình hiện tại |
| `/testalert` | Demo toàn bộ chuỗi wake alert (3 lần, cách 3 giây) |
| `/testntfy` | Test ntfy riêng biệt — báo kết quả ngay trong Telegram |

---

## Files thay đổi so với M1

```
backend/
  config.py         + NTFY_TOPIC (optional)
  session_store.py  + eta_window, wake_retry_count; IDLE làm default status
  scheduler.py      ++ ETA bands, smoothing, retry logic, ntfy alarm loop
  bot.py            + /testalert, /testntfy commands
  routes.py         + POST /telegram/webhook endpoint
  main.py           polling → webhook (set_webhook / delete_webhook trong lifespan)

Dockerfile          mới — production build
.dockerignore       mới
.env.example        + NTFY_TOPIC
docs/
  m2-overview.md    file này
```
