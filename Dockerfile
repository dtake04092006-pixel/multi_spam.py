# Sử dụng một ảnh (image) Python 3.11
FROM python:3.11-slim

# Cài đặt Tesseract OCR (BƯỚC QUAN TRỌNG)
# Đây là nơi duy nhất 'apt-get' sẽ hoạt động
RUN apt-get update && apt-get install -y tesseract-ocr

# Tạo thư mục làm việc trong container
WORKDIR /app

# Copy file requirements trước để tận dụng cache của Docker
COPY requirements.txt .

# Cài đặt các thư viện Python
RUN pip install -r requirements.txt

# Copy tất cả code của bạn (multi_spam_new.py, keywords/, v.v.)
COPY . .

# Lệnh để chạy app của bạn
# (Render sẽ tự động cung cấp biến $PORT)
CMD ["python", "multi_spam.py"]
