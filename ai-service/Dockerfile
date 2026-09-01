FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    fonts-noto-cjk \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# 1차 통합은 GPU가 아니라 CPU inference로 검증한다.
RUN pip install --no-cache-dir \
    torch==2.12.1 \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]