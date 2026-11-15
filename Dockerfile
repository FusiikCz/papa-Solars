FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]>=3.2"
COPY src ./src
COPY web ./web
COPY config.yaml run.py ./

ENV PYTHONPATH=/app/src
ENV DATABASE_URL=sqlite:///data/diag.db
EXPOSE 8080

CMD ["python", "run.py"]
