"""
End-to-end integration test cho Milestone 1.

Khong can Telegram that, khong can ORS that.
Tat ca external calls duoc mock.

Chay: python -m tests.test_e2e_m1
"""
import asyncio
import sys
import time
import unittest.mock as mock

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Setup: patch bot lifespan truoc khi import app
# ---------------------------------------------------------------------------

def _make_app_client():
    import backend.main as m

    with (
        mock.patch.object(m.bot_app, "initialize", return_value=None),
        mock.patch.object(m.bot_app, "start",      return_value=None),
        mock.patch.object(m.bot_app, "stop",        return_value=None),
        mock.patch.object(m.bot_app, "shutdown",    return_value=None),
        mock.patch.object(m.bot_app, "updater") as mu,
    ):
        mu.start_polling = mock.AsyncMock()
        mu.stop          = mock.AsyncMock()
        client = TestClient(m.app, raise_server_exceptions=True)
        return client, m.bot_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_query(data: str):
    query = mock.AsyncMock()
    query.data = data
    query.answer = mock.AsyncMock()
    query.edit_message_text = mock.AsyncMock()
    update = mock.MagicMock()
    update.callback_query = query
    ctx = mock.MagicMock()
    ctx.user_data = {}
    return update, ctx, query


def _run(coro):
    return asyncio.run(coro)


def ok(msg):
    print(f"  [PASS] {msg}")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    ok("GET /health -> 200")


def test_session_not_found(client):
    import backend.session_store as store
    store.clear_session()
    r = client.get("/session/current")
    assert r.status_code == 404
    ok("GET /session/current -> 404 when no session")


def test_miniapp_served_with_backend_url(client):
    r = client.get("/miniapp")
    assert r.status_code == 200
    assert "window.BACKEND_URL" in r.text
    assert "gps/update" in r.text
    assert "Transit Sleep Agent" in r.text
    ok("GET /miniapp -> HTML with injected BACKEND_URL + gps/update present")


def test_full_trip_flow(client, bot_app):
    """
    Happy path day du:
      bot: dest + prep -> session created
      miniapp: POST /trips/start with GPS
      miniapp: POST /gps/update (ETA far)
      GET /eta/current -> should_wake=False
      scheduler tick: ETA far -> no alert
      scheduler tick: ETA close -> WAKING + alert sent
      bot: wake_ack -> session cleared
    """
    import backend.session_store as store
    from backend.session_store import TripStatus
    from backend.destinations import DESTINATION_MAP
    from backend.scheduler import _tick
    from backend.bot import cb_wake_ack

    store.clear_session()

    # 1. Session creation (simulates bot dest+prep selection)
    dest = DESTINATION_MAP["ben_thanh"]
    store.create_session(dest.name, dest.coords, prep_time_seconds=300)
    s = store.get_session()
    # M2: session bắt đầu ở IDLE, chờ GPS đầu tiên từ Mini App
    assert s is not None and s.status == TripStatus.IDLE
    ok("Session created (dest+prep) → status=IDLE")

    # 2. GET /session/current
    r = client.get("/session/current")
    assert r.status_code == 200
    d = r.json()
    assert d["destination_name"] == dest.name
    assert d["prep_time_seconds"] == 300
    ok(f"GET /session/current -> prep=300s, status={d['status']}")

    # 3. POST /trips/start (first GPS from Mini App) → IDLE → ACTIVE
    r = client.post("/trips/start", json={"lat": 10.7725, "lon": 106.6980})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert store.get_session().last_lat == 10.7725
    # M2: /trips/start transitions IDLE → ACTIVE
    assert store.get_session().status == TripStatus.ACTIVE
    ok("POST /trips/start → IDLE→ACTIVE, GPS saved, ok=True")

    # 4. POST /gps/update (Mini App interval push, ETA far)
    eta_far = {"eta_seconds": 900.0, "distance_meters": 2500.0}
    with mock.patch("backend.routes.get_eta_async", return_value=eta_far):
        r = client.post("/gps/update", json={"lat": 10.773, "lon": 106.699})
    assert r.status_code == 200 and r.json()["eta_seconds"] == 900.0
    ok("POST /gps/update -> eta=900s returned to Mini App")

    # 5. GET /eta/current (debug)
    with mock.patch("backend.routes.get_eta_async", return_value=eta_far):
        r = client.get("/eta/current")
    assert r.status_code == 200
    d = r.json()
    assert d["should_wake"] is False
    ok(f"GET /eta/current -> should_wake=False (eta=900s, prep=300s)")

    # 6. Scheduler tick: ETA far -> no alert
    mock_bot = mock.AsyncMock()
    mock_bot.bot.send_message = mock.AsyncMock()
    with mock.patch("backend.scheduler.get_eta_async", return_value=eta_far):
        _run(_tick(mock_bot))
    mock_bot.bot.send_message.assert_not_called()
    assert store.get_session().status == TripStatus.ACTIVE
    ok("Scheduler tick (ETA far=900s) -> no alert, status=ACTIVE")

    # 7. Scheduler tick: ETA close -> WAKING + alert sent
    #    M2 (ETA smoothing): cần ít nhất 2 ticks với ETA gần để median window đạt <= prep_time
    #    Sau tick xa (900s) ở bước 6, eta_window=[900].
    #    Tick 7a: window=[900, 120], median=510 > 300 → chưa alert
    #    Tick 7b: window=[900, 120, 120], median=120 ≤ 300 → ALERT!
    eta_close = {"eta_seconds": 120.0, "distance_meters": 280.0}
    with mock.patch("backend.scheduler.get_eta_async", return_value=eta_close):
        _run(_tick(mock_bot))  # tick 7a: median=510, no alert yet
    mock_bot.bot.send_message.assert_not_called()
    assert store.get_session().status == TripStatus.ACTIVE
    ok("Scheduler tick 7a (ETA close=120s, window=[900,120]) → median=510 > prep → no alert yet")

    with mock.patch("backend.scheduler.get_eta_async", return_value=eta_close):
        _run(_tick(mock_bot))  # tick 7b: median=120, ALERT!
    mock_bot.bot.send_message.assert_called_once()
    call_kw = mock_bot.bot.send_message.call_args.kwargs
    markup_str = str(call_kw["reply_markup"])
    assert "wake_ack"    in markup_str
    assert "wake_snooze" in markup_str
    assert "wake_stop"   in markup_str
    assert store.get_session().status == TripStatus.WAKING
    ok("Scheduler tick 7b (ETA close=120s, window=[900,120,120]) → median=120 ≤ prep → WAKING + alert")

    # 8. wake_ack -> session cleared
    update, ctx, query = _fake_query("wake_ack")
    _run(cb_wake_ack(update, ctx))
    assert store.get_session() is None
    query.answer.assert_called_once()
    ok("wake_ack -> session cleared, answer() called")


def test_snooze_flow():
    """WAKING -> snooze -> alert blocked -> alert after expiry."""
    import backend.session_store as store
    from backend.session_store import TripStatus
    from backend.destinations import DESTINATION_MAP
    from backend.scheduler import _tick
    from backend.bot import cb_wake_snooze

    store.clear_session()
    dest = DESTINATION_MAP["landmark81"]
    store.create_session(dest.name, dest.coords, prep_time_seconds=300)
    s = store.get_session()
    s.last_lat, s.last_lon = 10.795, 106.7218
    s.status = TripStatus.WAKING

    mock_bot = mock.AsyncMock()
    mock_bot.bot.send_message = mock.AsyncMock()
    eta_close = {"eta_seconds": 180.0, "distance_meters": 350.0}

    # Snooze
    update, ctx, _ = _fake_query("wake_snooze")
    _run(cb_wake_snooze(update, ctx))
    assert s.status == TripStatus.ACTIVE
    assert s.snooze_until is not None and s.snooze_until > time.time()
    ok("wake_snooze -> status=ACTIVE, snooze_until set in future")

    # Tick during snooze: blocked
    with mock.patch("backend.scheduler.get_eta_async", return_value=eta_close):
        _run(_tick(mock_bot))
    mock_bot.bot.send_message.assert_not_called()
    ok("Scheduler tick during snooze -> no alert (blocked)")

    # Expire snooze -> alert fires
    s.snooze_until = time.time() - 1
    with mock.patch("backend.scheduler.get_eta_async", return_value=eta_close):
        _run(_tick(mock_bot))
    mock_bot.bot.send_message.assert_called_once()
    assert s.status == TripStatus.WAKING
    ok("Scheduler tick after snooze expiry -> alert sent, status=WAKING")


def test_stop_flow():
    import backend.session_store as store
    from backend.destinations import DESTINATION_MAP
    from backend.bot import cb_wake_stop

    dest = DESTINATION_MAP["mien_dong"]
    store.create_session(dest.name, dest.coords, 300)
    assert store.get_session() is not None

    update, ctx, query = _fake_query("wake_stop")
    _run(cb_wake_stop(update, ctx))
    assert store.get_session() is None
    query.answer.assert_called_once()
    ok("wake_stop -> session cleared, answer() called")


def test_gps_not_found_blocks_eta():
    """eta/current returns 425 if no GPS yet."""
    import backend.session_store as store
    from backend.destinations import DESTINATION_MAP
    import backend.main as m
    import unittest.mock as mock

    store.clear_session()
    dest = DESTINATION_MAP["thu_duc_station"]
    store.create_session(dest.name, dest.coords, 300)

    with (
        mock.patch.object(m.bot_app, "initialize", return_value=None),
        mock.patch.object(m.bot_app, "start",      return_value=None),
        mock.patch.object(m.bot_app, "stop",        return_value=None),
        mock.patch.object(m.bot_app, "shutdown",    return_value=None),
        mock.patch.object(m.bot_app, "updater") as mu,
    ):
        mu.start_polling = mock.AsyncMock()
        mu.stop          = mock.AsyncMock()
        client = TestClient(m.app)
        r = client.get("/eta/current")
        assert r.status_code == 425
        ok("GET /eta/current (no GPS) -> 425 Too Early")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all():
    print()
    print("=== Milestone 1 - End-to-End Integration Test ===")
    print()

    client, bot_app = _make_app_client()

    suites = [
        ("Health check",            lambda: test_health(client)),
        ("Session 404",             lambda: test_session_not_found(client)),
        ("Mini App HTML",           lambda: test_miniapp_served_with_backend_url(client)),
        ("Full trip flow",          lambda: test_full_trip_flow(client, bot_app)),
        ("Snooze flow",             lambda: test_snooze_flow()),
        ("Stop flow",               lambda: test_stop_flow()),
        ("ETA blocked (no GPS)",    lambda: test_gps_not_found_blocks_eta()),
    ]

    passed = failed = 0
    for name, fn in suites:
        print(f"\n[{name}]")
        try:
            fn()
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  [FAIL] {exc}")
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    print()

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run_all()
