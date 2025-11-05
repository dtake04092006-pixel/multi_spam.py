#!/usr/bin/env bash
# exit on error
set -o errexit

# Cài đặt các thư viện hệ thống
apt-get update
apt-get install -y tesseract-ocr

# Chạy pip install cho requirements.txt
pip install -r requirements.txt
