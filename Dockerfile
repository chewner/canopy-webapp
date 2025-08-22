
# Deployable Docker image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for pandas/mpl
RUN apt-get update && apt-get install -y build-essential gcc g++ libfreetype6-dev libpng-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

EXPOSE 8000
CMD ["gunicorn", "app:app", "-c", "gunicorn.conf.py"]
