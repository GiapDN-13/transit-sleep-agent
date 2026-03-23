# Milestone 1 — MVP End-to-End

## Mục tiêu

Xây dựng luồng hoàn chỉnh từ đầu đến cuối:
user chọn điểm xuống trong Telegram → Mini App gửi GPS → backend tính ETA → bot báo thức khi sắp đến trạm.

---

## Kiến trúc tổng quan

```
┌──────────────────────────────────────────────────────────────────┐
│  Telegram Client (điện thoại user)                               │
│                                                                  │
│  ┌─────────────────┐          ┌──────────────────────────────┐  │
│  │   Telegram Bot  │  inline  │     Telegram Mini App        │  │
│  │   (chat UI)     │◄────────►│  (WebView nhúng trong Tele)  │  │
│  └────────┬────────┘  keyboard│  - Pick mode: chọn bản đồ   │  │
│           │                   │  - Track mode: gửi GPS       │  │
│           │ polling            └──────────────┬───────────────┘  │
└───────────┼──────────────────────────────────┼──────────────────┘
            │                                  │ HTTPS (ngrok)
            │ Bot API                          │ POST /trips/start
            ▼                                  │ POST /gps/update
┌───────────────────────────────────────────────────────────────┐
│  Backend (FastAPI + uvicorn, localhost:8001)                   │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌───────────┐  │
│  │  bot.py  │  │ routes.py│  │scheduler.py│  │ors_client │  │
│  │ handlers │  │ REST API │  │ poll loop  │  │ (ORS ETA) │  │
│  └────┬─────┘  └────┬─────┘  └─────┬──────┘  └─────┬─────┘  │
│       │             │               │                │        │
│       └─────────────┴───────────────┘                │        │
│                     │ read/write                      │        │
│              ┌──────▼──────┐          ┌──────────────▼──────┐ │
│              │session_store│          │  OpenRouteService   │ │
│              │ (RAM only)  │          │  (external API)     │ │
│              └─────────────┘          └─────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

### Các thành phần

| File | Vai trò |
|------|---------|
| `backend/main.py` | FastAPI app entry point; quản lý lifespan bot + scheduler |
| `backend/bot.py` | Toàn bộ Telegram bot handlers + keyboard builders |
| `backend/routes.py` | REST API endpoints cho Mini App gọi |
| `backend/scheduler.py` | Background loop poll ETA mỗi 30s, gửi wake alert |
| `backend/session_store.py` | In-memory session (1 session toàn cục, 1 user) |
| `backend/ors_client.py` | Wrapper async quanh thư viện `openrouteservice` |
| `backend/destinations.py` | Danh sách hard-coded điểm xuống + prep time options |
| `backend/config.py` | Load env vars; fail-fast nếu thiếu biến nào |
| `miniapp/index.html` | Telegram Mini App (HTML/CSS/JS thuần) |

---

## Session State Machine

```
                   /start hoặc restart
                         │
                         ▼
                      ┌──────┐
                      │ IDLE │  (trạng thái khởi tạo — thực tế không dùng ở M1)
                      └──┬───┘
                         │  create_session() sau khi user chọn dest + prep
                         ▼
                      ┌────────┐
             ┌────────│ ACTIVE │◄────────────────────────┐
             │        └───┬────┘                         │
             │            │  ETA ≤ prep_time_seconds      │
             │            ▼                              │
             │        ┌────────┐                         │
             │        │ WAKING │  wake alert đã gửi      │
             │        └───┬────┘                         │
             │            │                              │
             │     ┌──────┴──────────┐                  │
             │     │                 │ wake_snooze        │
             │     │ wake_ack /      └──────────────────►┘
             │     │ wake_stop                (→ ACTIVE, snooze 5 phút)
             │     ▼
             │  ┌──────┐
             │  │ DONE │  session cleared (= None)
             │  └──────┘
             │
             └── /start bất kỳ lúc nào → clear session, quay đầu
```

**Lưu ý M1**: `IDLE` được define trong enum nhưng không được set trong code — session luôn được tạo thẳng ở `ACTIVE`.

---

## Luồng người dùng hoàn chỉnh

### Nhánh A — Chọn điểm từ danh sách preset

```
User                    Bot (bot.py)             FastAPI (routes.py)     Scheduler
 │                          │                          │                     │
 │──── /start ─────────────►│                          │                     │
 │                          │ reply: ReplyKeyboard     │                     │
 │◄─────────────────────────│ (nút bản đồ)             │                     │
 │                          │ + InlineKeyboard         │                     │
 │◄─────────────────────────│ (danh sách preset)       │                     │
 │                          │                          │                     │
 │── tap "Chợ Bến Thành" ──►│                          │                     │
 │                          │ cb_destination()         │                     │
 │◄─────────────────────────│ edit: hỏi prep time      │                     │
 │                          │                          │                     │
 │── tap "5 phút" ─────────►│                          │                     │
 │                          │ cb_prep_time()           │                     │
 │                          │ store.create_session()   │                     │
 │◄─────────────────────────│ edit: xác nhận + nút     │                     │
 │                          │ "Bắt đầu theo dõi"       │                     │
 │                          │ (InlineKeyboard,          │                     │
 │                          │  web_app=track mode)      │                     │
 │                          │                          │                     │
 │── tap "Bắt đầu" ────────►│ (mở Mini App track mode) │                     │
 │  [Mini App opens]        │                          │                     │
 │── loadSession() ────────────────────────────────────►GET /session/current │
 │◄──────────────────────────────────────────────── 200 {dest, prep, status}─┤
 │                          │                          │                     │
 │── tap "Lấy vị trí" ──    │                          │                     │
 │   [GPS acquired]         │                          │                     │
 │── postGps() ────────────────────────────────────────►POST /trips/start    │
 │◄──────────────────────────────────────────────── 200 {ok: true} ──────────┤
 │                          │                          │                     │
 │   [polling starts]       │                          │                     │
 │── gpsTick() every 30s ──────────────────────────────►POST /gps/update     │
 │◄──────────────────────────────────────────── 200 {eta_seconds, dist} ─────┤
 │                          │                          │                     │
 │                          │                  ◄── _tick() every 30s ────────┤
 │                          │                          │  get_eta_async(ORS) │
 │                          │                          │  eta ≤ prep?        │
 │                          │  send_wake_alert() ──────┤         │           │
 │◄─── ⏰ SẮP ĐẾN TRẠM! ───│  [với 3 nút]             │  status=WAKING      │
 │                          │                          │                     │
 │── tap "✅ Tôi dậy rồi" ──►│                          │                     │
 │                          │ cb_wake_ack()            │                     │
 │                          │ store.clear_session()    │                     │
 │◄─────────────────────────│ "Chúc xuống xe an toàn"  │                     │
```

### Nhánh B — Chọn điểm từ bản đồ (pick mode)

```
User                    Bot (bot.py)             Mini App (pick mode)
 │                          │                          │
 │──── /start ─────────────►│                          │
 │◄─────────────────────────│ ReplyKeyboard: nút bản đồ│
 │◄─────────────────────────│ InlineKeyboard: presets  │
 │                          │                          │
 │── tap nút bản đồ ───────►│ (mở Mini App pick mode)  │
 │  [Mini App opens]        │                          │
 │─────────────────────────────────────────────────────► init map (Leaflet)
 │                          │                          │ show user location
 │                          │                          │ show preset markers
 │── tap điểm trên bản đồ ─────────────────────────────► reverse geocode (Nominatim)
 │                          │                          │ selectDest(name, lat, lon)
 │── tap "✓ Xác nhận" ─────────────────────────────────► tg.sendData(JSON)
 │                          │                          │ [Mini App closes]
 │                          │                          │
 │                    handle_webapp_data()             │
 │                    ← parse {name, lat, lon}         │
 │                    context.user_data["destination"] │
 │◄─────────────────────────│ ReplyKeyboardRemove      │
 │◄─────────────────────────│ hỏi prep time (InlineKB) │
 │                          │                          │
 │  [... tiếp tục như nhánh A từ bước chọn prep time]
```

---

## REST API Endpoints

| Method | Path | Caller | Mô tả |
|--------|------|--------|-------|
| `GET` | `/health` | Debug / monitor | Kiểm tra server + bot username |
| `GET` | `/miniapp` | Telegram (WebView) | Serve HTML với config injected |
| `GET` | `/session/current` | Mini App (track mode) | Lấy dest + prep time hiện tại |
| `POST` | `/trips/start` | Mini App (track mode) | GPS đầu tiên → kích hoạt ACTIVE |
| `POST` | `/gps/update` | Mini App (track mode) | GPS định kỳ 30s + tính ETA |
| `GET` | `/eta/current` | Debug | ETA on-demand từ GPS cuối |

### `/miniapp` — Config injection

Server inject vào `<head>` trước khi trả HTML:
```html
<script>
  window.BACKEND_URL = "https://xxxx.ngrok-free.app";
  window.PRESET_DESTINATIONS = [{ id, name, lat, lon }, ...];
</script>
```

Mini App đọc `window.BACKEND_URL` để biết gọi API về đâu (quan trọng khi URL ngrok thay đổi).

---

## Bot Commands & Handlers

| Trigger | Handler | Hành động |
|---------|---------|-----------|
| `/start` | `cmd_start` | Clear session, gửi 2 keyboard (bản đồ + preset) |
| `/help` | `cmd_help` | Hướng dẫn sử dụng |
| `/status` | `cmd_status` | Hiển thị trạng thái session hiện tại |
| Callback `dest:<id>` | `cb_destination` | Lưu preset vào `user_data`, hỏi prep time |
| Callback `prep:<seconds>` | `cb_prep_time` | Tạo session, hiện nút "Bắt đầu theo dõi" |
| Callback `restart` | `cb_restart` | Clear session, gửi lại 2 keyboard |
| Callback `wake_ack` | `cb_wake_ack` | Xác nhận dậy, clear session |
| Callback `wake_snooze` | `cb_wake_snooze` | WAKING → ACTIVE, snooze 5 phút |
| Callback `wake_stop` | `cb_wake_stop` | Dừng hoàn toàn, clear session |
| `web_app_data` message | `handle_webapp_data` | Parse {name, lat, lon} từ pick mode |

---

## Scheduler — ETA Polling Loop

```python
# Chạy mỗi POLL_INTERVAL = 30 giây
async def _tick(bot_app):
    session = store.get_session()
    if not session or session.status != ACTIVE:
        return
    if snooze_until and now < snooze_until:
        return           # đang snooze, bỏ qua
    if no GPS:
        return           # chưa có GPS, bỏ qua

    result = await get_eta_async(current_coords, dest_coords)  # gọi ORS
    session.last_eta_seconds = result["eta_seconds"]

    if eta <= prep_time_seconds:
        session.status = WAKING
        await send_wake_alert(bot_app, session)  # gửi tin nhắn Telegram
```

**Lưu ý**: Sau khi chuyển sang `WAKING`, scheduler **dừng hẳn** (không check tiếp). Alert chỉ được gửi 1 lần cho đến khi user snooze (→ ACTIVE) hoặc stop.

---

## ORS Client

- Thư viện `openrouteservice` là **synchronous** → wrap trong `asyncio.to_thread()` để không block event loop FastAPI.
- Profile: `driving-car` (phù hợp tuyến bus theo đường ô tô).
- Coordinates format: `(longitude, latitude)` — chuẩn ORS, **ngược với Leaflet** (lat, lon).
- Trả về: `{ eta_seconds: float, distance_meters: float }`.

---

## Config & Environment

| Biến | Mô tả |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | Token từ @BotFather |
| `ORS_API_KEY` | Key từ openrouteservice.org |
| `BACKEND_URL` | URL public của backend (ngrok HTTPS) |
| `MINI_APP_URL` | `BACKEND_URL/miniapp` |
| `OWNER_CHAT_ID` | Telegram chat ID của user duy nhất |

Tất cả đều **bắt buộc** — thiếu bất kỳ biến nào sẽ raise `EnvironmentError` ngay khi import `config`.

---

## Giới hạn của M1 (→ input cho M2)

| # | Hạn chế | Ảnh hưởng |
|---|---------|-----------|
| 1 | Session chỉ lưu trong RAM | Restart server = mất hành trình |
| 2 | Scheduler poll cứng 30s bất kể ETA | Gọi ORS nhiều khi ETA còn 2 tiếng |
| 3 | Wake alert chỉ gửi 1 lần, không retry | Nếu user không thấy thông báo = ngủ quên |
| 4 | `IDLE` enum define nhưng không dùng | State machine chưa đầy đủ |
| 5 | Không có giới hạn cho session zombie | Session tồn tại mãi nếu không có GPS |
| 6 | ETA thô từ ORS, không smoothing | Nhiễu GPS → ETA nhảy loạn → false alarm |
| 7 | Không có trip history / logging | Không biết app đã hoạt động thế nào |
