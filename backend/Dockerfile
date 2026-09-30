FROM python:3.13-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
RUN useradd -m nexa && chown -R nexa /srv
USER nexa
EXPOSE 8000
# One process: the in-process WebSocket hub and request sweeper are per-process (see README "Scaling").
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
