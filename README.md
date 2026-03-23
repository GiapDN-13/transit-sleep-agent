# Transit Sleep Agent

Ứng dụng cá nhân chống ngủ quên lố trạm trên xe bus.  
Giao diện: Telegram Bot + Telegram Mini App.  
ETA provider: OpenRouteService (ORS).

## Cấu trúc dự án

```
backend/
  config.py        # Load env vars, fail-fast nếu thiếu
  main.py          # FastAPI app, serve miniapp static
  bot.py           # Telegram bot handlers
  ors_client.py    # Wrapper gọi ORS Directions API
  session_store.py # In-memory trip session (1 user)
  scheduler.py     # ETA polling loop

miniapp/
  index.html       # Telegram Mini App (HTML + JS)
```

## Setup chi tiết

### Bước 1 — Cài dependencies

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

---

### Bước 2 — Lấy `TELEGRAM_BOT_TOKEN`

1. Mở Telegram, tìm **@BotFather**
2. Gửi lệnh `/newbot`
3. Đặt tên hiển thị, ví dụ: `Transit Sleep Agent`
4. Đặt username (phải kết thúc bằng `bot`), ví dụ: `my_transit_sleep_bot`
5. BotFather trả về token dạng: `7xxxxxxxxx:AAxxxxxx-xxxxxxxxxxxxxxxxxxxxxx`
6. Copy giá trị đó vào `TELEGRAM_BOT_TOKEN`

---

### Bước 3 — Lấy `ORS_API_KEY`

1. Truy cập [openrouteservice.org](https://openrouteservice.org/dev/#/signup) → đăng ký tài khoản miễn phí
2. Sau khi xác nhận email, vào **Dashboard → API Keys**
3. Key mặc định đã được tạo sẵn (hoặc bấm **Add Key**)
4. Copy key vào `ORS_API_KEY`

> Free tier: 2.000 requests/ngày, 40 requests/phút — đủ dùng cho cá nhân.

---

### Bước 4 — Lấy `OWNER_CHAT_ID`

1. Mở Telegram, tìm **@userinfobot**
2. Gửi bất kỳ tin nhắn nào
3. Bot trả về thông tin, trong đó có dòng `Id: 123456789`
4. Copy số đó vào `OWNER_CHAT_ID`

---

### Bước 5 — Lấy `BACKEND_URL` và `MINI_APP_URL` (dùng ngrok cho dev)

Telegram Mini App **bắt buộc HTTPS**. Dùng ngrok để tạo tunnel từ localhost ra internet.

1. Tải và cài [ngrok](https://ngrok.com/download) (miễn phí)
2. Đăng ký tài khoản ngrok → lấy authtoken → chạy một lần:
   ```bash
   ngrok config add-authtoken <your_authtoken>
   ```
3. Mỗi lần dev, chạy:
   ```bash
   ngrok http 8000
   ```
4. ngrok hiển thị URL dạng: `https://xxxx-xx-xx-xx-xx.ngrok-free.app`
5. Copy URL đó:
   - `BACKEND_URL=https://xxxx-xx-xx-xx-xx.ngrok-free.app`
   - `MINI_APP_URL=https://xxxx-xx-xx-xx-xx.ngrok-free.app/miniapp`

> Lưu ý: URL ngrok thay đổi mỗi lần restart (ở free tier). Phải cập nhật lại `.env` và restart backend mỗi lần.

---

### Bước 6 — Tạo file `.env`

```bash
cp .env.example .env
```

Mở `.env` và điền đầy đủ 5 giá trị:

```env
TELEGRAM_BOT_TOKEN=7xxxxxxxxx:AAxxxxxx-xxxxxxxxxxxxxxxxxxxxxx
ORS_API_KEY=eyJvcm...
BACKEND_URL=https://xxxx-xx-xx-xx-xx.ngrok-free.app
MINI_APP_URL=https://xxxx-xx-xx-xx-xx.ngrok-free.app/miniapp
OWNER_CHAT_ID=123456789
```

---

### Bước 7 — Chạy backend

```bash
# Terminal 1 — ngrok tunnel (giữ chạy)
ngrok http 8000

# Terminal 2 — backend
uvicorn backend.main:app --reload --port 8000
```

Kiểm tra: truy cập `http://localhost:8000/health` → phải trả về `{"status": "ok"}`

### Chạy integration test

```bash
python -m tests.test_e2e_m1
```

## Milestones

| Milestone | Mô tả | Status |
|---|---|---|
| M1 | MVP end-to-end | ✅ Done |
| M2 | Stability, state machine, Koyeb deploy | 🔄 In progress |
| M3 | AI-lite movement analysis | ⏳ |
| M4 | Personalization | ⏳ |
