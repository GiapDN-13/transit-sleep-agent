# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────
#  Transit Sleep Agent — Production Dockerfile
#  Base: python:3.12-slim
# ─────────────────────────────────────────────

FROM python:3.12-slim

# Không tạo .pyc, log ra stdout ngay lập tức (quan trọng cho Koyeb log viewer)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Cài dependencies trước (layer cache — chỉ rebuild khi requirements.txt thay đổi)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY backend/ ./backend/
COPY miniapp/  ./miniapp/

# Koyeb expose port 8000 theo mặc định
EXPOSE 8000

# Chạy production — KHÔNG dùng --reload
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
