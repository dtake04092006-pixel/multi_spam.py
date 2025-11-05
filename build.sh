#!/usr/bin/env bash
# exit on error
set -o errexit

# Thêm sudo vào 2 dòng dưới
sudo apt-get update
sudo apt-get install -y tesseract-ocr

# Dòng này giữ nguyên
pip install -r requirements.txt
