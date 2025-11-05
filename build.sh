#!/usr/bin/env bash
# exit on error
set -o errexit

# Tạo thư mục bị thiếu mà log lỗi đầu tiên đã báo
mkdir -p /var/lib/apt/lists/partial

# Chạy lệnh (không cần sudo vì đã là root)
apt-get update
apt-get install -y tesseract-ocr

# Chạy pip install
pip install -r requirements.txt
