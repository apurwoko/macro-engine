# Deploy ke VPS Ubuntu (22.04/24.04)

> **Belum diuji di VPS publik sungguhan.** `docker compose build`, `backfill` penuh (FRED/EIA/COT/Yahoo/RSS),
> `calibrate`, dan `api`/`scheduler` **sudah** dijalankan dan diverifikasi sekali di mesin Ubuntu nyata
> dengan MySQL 8 yang sudah terpasang (bukan container `mysql`) — lihat `docs/SETUP_LOG.md` untuk
> kronologi lengkap termasuk dua bug yang ditemukan & diperbaiki saat setup itu. Jalur "MySQL
> container bawaan compose" (langkah 1-4 di bawah) masih belum pernah dicoba end-to-end; jalur
> "pakai MySQL yang sudah ada" (§1b) sudah.

Spesifikasi cukup: 2 vCPU, 2–4 GB RAM, 20 GB disk.

## 1. Server & Docker
```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ca-certificates curl ufw unzip
# Docker resmi
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update && sudo apt -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER   # logout/login sekali

# Firewall: hanya SSH (dan 80/443 bila nanti pasang dashboard Laravel)
sudo ufw allow OpenSSH && sudo ufw enable
```
MySQL dan API di compose hanya bind ke `127.0.0.1`, jadi tidak terbuka ke internet. Jangan ubah itu.
(Catatan: Docker memanipulasi iptables dan bisa melewati ufw untuk port yang dipublikasikan ke `0.0.0.0`; karena bind `127.0.0.1`, aman.)

## 1b. Memakai MySQL yang sudah ada (alternatif ke container `mysql`)

Bila VPS sudah punya MySQL 8 terpasang untuk proyek lain dan kamu ingin satu instance dipakai bersama
(hindari volume Docker terpisah untuk DB ini), pakai jalur ini **sebagai pengganti** `docker compose
up -d mysql` di §3. Diverifikasi end-to-end di `docs/SETUP_LOG.md`.

1. **Nonaktifkan service `mysql` compose** lewat `docker-compose.override.yml` (jangan edit
   `docker-compose.yml` langsung):
   ```yaml
   services:
     mysql:
       profiles: ["internal-db"]   # tidak pernah start tanpa --profile internal-db
     api:
       depends_on: !reset {}        # hapus total dependency ke mysql (service itu tidak jalan)
       extra_hosts:
         - "host.docker.internal:host-gateway"
     scheduler:
       depends_on: !reset {}
       extra_hosts:
         - "host.docker.internal:host-gateway"
   ```
2. **`.env`**: `MYSQL_HOST=host.docker.internal`, `MYSQL_PORT=3306` (port MySQL host, biasanya tetap
   3306), `MYSQL_DATABASE`/`MYSQL_USER`/`MYSQL_PASSWORD` sesuai yang akan dibuat di langkah 3.
3. **Buat DB + user + bind-address lewat SATU skrip sudo** (jangan jalankan perintah sudo satu-satu):
   lihat `deploy/sudo_steps.sh` di repo ini — idempoten, membuat database `macro` + user
   `macro`@`172.%` (BUKAN `%`, BUKAN root), memuat `db/init/001_schema.sql`, dan membuka
   `bind-address` MySQL host ke IP bridge **`docker0`** (biasanya `172.17.0.1`, cek dengan
   `ip -4 addr show docker0`) di samping `127.0.0.1` yang sudah ada. Jalankan:
   ```bash
   sudo bash deploy/sudo_steps.sh
   ```
   **Catatan penting (ditemukan empiris, bukan dari dokumentasi Docker)**: nilai `host-gateway` pada
   `extra_hosts` di Linux SELALU resolve ke gateway bridge **default `docker0`**, BUKAN ke gateway
   network compose project ini (`macro-engine_default` atau sejenisnya) — walau container `api`/
   `scheduler` berjalan di network project itu, bukan di `docker0` langsung. Jangan bind MySQL ke
   gateway network compose; bind ke `docker0`.
4. Verifikasi sebelum lanjut ke `backfill`:
   ```bash
   docker compose config --no-interpolate   # pastikan service mysql TIDAK muncul (profile tidak aktif)
                                             # --no-interpolate: jangan sampai mencetak isi .env (lihat docs/SETUP_LOG.md §2)
   docker compose build
   docker compose run --rm api python -c "from app import db; print(db.scalar('SELECT @@session.time_zone'))"
   # harus mencetak: +00:00
   ```
5. Lanjut ke §3 di bawah **mulai dari `docker compose run --rm api python -m app.cli backfill`**
   (lewati `docker compose up -d mysql` — service itu memang sengaja tidak pernah start).

Tes integrasi (`MACRO_INTEGRATION_DB=1`) **jangan** diarahkan ke DB `macro` produksi — buat DB sekali
pakai terpisah (`deploy/sudo_steps.sh` juga membuat `macro_test` + user sendiri untuk ini).

## 2. Unggah proyek & isi `.env`
```bash
scp macro-engine.zip user@IP_VPS:~ ; ssh user@IP_VPS
unzip macro-engine.zip && cd macro-engine
cp .env.example .env && chmod 600 .env
openssl rand -hex 32        # tempel sebagai API_KEY; buat juga MYSQL_ROOT_PASSWORD & MYSQL_PASSWORD yang kuat
nano .env                   # isi FRED_API_KEY (gratis), EIA_API_KEY (gratis); ANTHROPIC_API_KEY & TELEGRAM_* opsional
mkdir -p reports && sudo chown 1000:1000 reports
```

## 3. Jalankan pertama kali (urutan penting)

> Memakai MySQL yang sudah ada (§1b)? Lewati baris `docker compose up -d mysql` — service itu sengaja
> tidak pernah start (profile `internal-db`). `backfill` tetap jalan sama seperti di bawah.

```bash
docker compose build
docker compose up -d mysql                       # LEWATI bila pakai §1b (MySQL host sendiri)
docker compose run --rm api python -m app.cli backfill      # ingest penuh + betas + skor (beberapa menit)
docker compose run --rm api python -m app.cli backtest XAUUSD
docker compose run --rm api python -m app.cli calibrate      # walk-forward semua aset -> ./reports/calibration_*/
docker compose up -d api scheduler
```
Periksa log `backfill` dengan teliti: bagian yang **belum terverifikasi** (nama kolom & kode kontrak COT, route EIA,
simbol Yahoo, URL RSS) paling mungkin gagal di sini. Aset yang datanya kosong akan tertulis "DILEWATI" di kalibrasi.

Hasilnya ada di `~/macro-engine/reports/calibration_YYYYmmdd_HHMM/`:
`summary.csv`, satu `<ASET>.md` per aset, `panel_<ASET>.csv`, dan `suggested_factors.yaml` (usulan; **tidak** menimpa config).

## 4. Operasional
```bash
docker compose logs -f scheduler          # job harian/mingguan
docker compose ps
curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/health
```
Backup harian (cron `crontab -e`) — **container `mysql` bawaan compose** (bukan §1b):
```
15 3 * * * cd ~/macro-engine && set -a && . ./.env && set +a && docker compose exec -T mysql mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction macro | gzip > ~/backup/macro_$(date +\%F).sql.gz && find ~/backup -mtime +14 -delete
```
**MySQL host sendiri (§1b)**: tidak ada container `mysql` untuk `docker compose exec`; backup lewat
`mysqldump` langsung ke host — lihat `docs/RUNBOOK.md` § Backup (perlu kredensial root MySQL host
yang sesungguhnya, BUKAN `MYSQL_ROOT_PASSWORD` di `.env` yang hanya dipakai container `mysql` yang
dinonaktifkan).
(`mkdir -p ~/backup` dulu.)

## 5. Peringatan
- **Yahoo (yfinance) dari IP datacenter sering kena rate-limit/blokir.** Bila `ingest prices` gagal, harga adalah
  masukan wajib kalibrasi & repricing; ganti sumber harga (mis. Twelve Data / Alpha Vantage / Stooq) di `ingest/prices.py`.
- Dashboard Laravel dijalankan di host (lihat `dashboard/README.md`), arahkan ke `http://127.0.0.1:8000`; bila dibuka ke publik,
  pasang Nginx + HTTPS dan login.
- Ubah bobot hanya lewat `engine/config/factors.yaml` lalu `docker compose restart api scheduler`.
