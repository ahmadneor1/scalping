FROM python:3.12-slim

WORKDIR /app

# Instal sertifikat SSL root agar Python bisa melakukan koneksi HTTPS aman
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

# Salin seluruh isi folder proyek ke dalam container
COPY . /app/

# Instal pustaka yang dibutuhkan (termasuk ccxt untuk versi pro/websocket)
RUN pip install --no-cache-dir ccxt pandas requests

# Jalankan skrip utama bot secara otomatis
CMD ["python", "run.py"]