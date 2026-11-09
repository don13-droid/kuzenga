FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements/production.txt requirements/base.txt ./requirements/
RUN pip install --no-cache-dir -r requirements/production.txt
COPY . .
RUN addgroup --system django && adduser --system --ingroup django django \
    && chown -R django:django /app
USER django

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--error-logfile", "-"]
