FROM python:3.11-slim

WORKDIR /app/project_backend

ENV RUNNING_IN_DOCKER=1

RUN apt-get update && apt-get install -y gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["sh", "-c", "echo \"PostgreSQL: ${POSTGRES_USER}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}\" && python wait_for_db.py && python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:5000"]
