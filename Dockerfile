FROM python:3.11-slim

WORKDIR /app/project_backend

ENV RUNNING_IN_DOCKER=1

RUN apt-get update && apt-get install -y gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["sh", "-c", "echo \"Django PostgreSQL: ${POSTGRES_USER}@${POSTGRES_HOST}:${POSTGRES_PORT}/${DJANGO_POSTGRES_DB:-student}\" && python wait_for_db.py && if [ \"${RUN_DJANGO_MIGRATIONS:-0}\" = \"1\" ]; then python manage.py migrate --noinput; fi && if [ \"${RUN_ENERGY_INDEXES:-0}\" = \"1\" ]; then python manage.py ensure_energy_indexes; fi && python manage.py runserver 0.0.0.0:5000"]
