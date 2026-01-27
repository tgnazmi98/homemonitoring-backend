FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

RUN python manage.py collectstatic --noinput || echo "collectstatic will run after project creation"

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "electrical_monitoring.wsgi:application"]