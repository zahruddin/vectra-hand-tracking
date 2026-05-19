# Gunakan image Python ringan
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install dependency sistem yang dibutuhkan OpenCV
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy sisa kode
COPY . .

# Jalankan server
CMD ["python", "homeweb.py"]