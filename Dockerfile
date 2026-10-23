# RefundWise AI: python run.py --serve on port 8000. Scout Intent needs Node.js 18+.
FROM python:3.11-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/logs
ENV SAMPLE_MODE=false
EXPOSE 8000
CMD ["python", "run.py", "--serve", "--host", "0.0.0.0", "--port", "8000"]
