FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

COPY requirements/base.txt requirements/production.txt requirements/constraints.txt ./requirements/
RUN python -m pip install --no-cache-dir -r requirements/production.txt

RUN addgroup --system django \
    && adduser --system --ingroup django django \
    && mkdir -p /app/media /app/staticfiles \
    && chown django:django /app/media /app/staticfiles
COPY --chown=django:django . .

USER django
EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--error-logfile", "-"]
