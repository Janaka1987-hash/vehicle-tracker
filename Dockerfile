FROM python:3.11-slim

# Tesseract OCR සහ අවශ්‍ය පද්ධති පැකේජ ස්ථාපනය කිරීම
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "--worker-class", "gthread", "--threads", "100", "-w", "1", "--bind", "0.0.0.0:8080", "app:app"]
