# Runbook operasional

Asumsi: setup sudah selesai sesuai `docs/SETUP_LOG.md` (MySQL host, `deploy/sudo_steps.sh` sudah
dijalankan, `docker-compose.override.yml` terpasang).

## Start / stop

```bash
# start (api + scheduler; mysql TIDAK ikut -- service itu dinonaktifkan via profile)
docker compose up -d api scheduler

# stop (aman: tidak menyentuh data, data ada di MySQL host bukan volume Docker)
docker compose stop api scheduler

# restart setelah ubah .env atau config/*.yaml
docker compose restart api scheduler

# JANGAN jalankan ini kecuali benar-benar ingin hapus network/container (data MySQL tetap aman
# karena di host, tapi tetap tidak perlu kecuali troubleshooting jaringan):
#   docker compose down         (TANPA -v)
# JANGAN PERNAH: docker compose down -v  -- tidak ada volume Docker untuk DB di setup ini,
# tapi tetap dilarang secara umum di proyek ini.
```

## Melihat log

```bash
docker compose logs -f scheduler        # job harian/mingguan, status terjadwal
docker compose logs -f api              # request API
docker compose ps                       # status container
tail -f logs/backfill_*.log             # log backfill manual terakhir (jika pernah dijalankan ulang)
```

Status job di DB: `SELECT * FROM job_runs ORDER BY started_at DESC LIMIT 20;` (lewat `mysql` sebagai
`macro`/`macro_test` dari container, atau `root` dari host via `sudo mysql`).

## Cek kesehatan cepat

```bash
curl -s http://127.0.0.1:8000/health
# dengan auth (ambil API_KEY dari .env tanpa mencetaknya ke tempat lain):
set -a; source .env; set +a
curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/bias | python3 -m json.tool
```

## Backup (hanya DB `macro`, bukan database lain di MySQL host)

```bash
set -a; source .env; set +a
mkdir -p ~/backup
mysqldump -h 127.0.0.1 -u root -p"<password root MySQL HOST, bukan MYSQL_ROOT_PASSWORD di .env>" \
  --single-transaction macro | gzip > ~/backup/macro_$(date +%F).sql.gz
```

> **Penting**: `MYSQL_ROOT_PASSWORD` di `.env` adalah sisa dari skema "container mysql" yang di proyek
> ini **dinonaktifkan** (lihat keputusan #1/#3) — itu BUKAN password root MySQL host yang sesungguhnya.
> Backup harus pakai kredensial root MySQL host yang asli (biasanya hanya bisa lewat `sudo mysql` /
> auth_socket, atau akun admin terpisah yang kamu buat khusus untuk backup — bukan root auth_socket,
> karena `mysqldump -h 127.0.0.1` adalah koneksi TCP, bukan socket, jadi auth_socket tidak berlaku).
> Rekomendasi: buat user backup khusus `backup`@`localhost` dengan `SELECT, LOCK TABLES, SHOW VIEW`
> di `macro.*` lewat `sudo mysql` sekali, lalu pakai kredensial itu di cron — **belum dibuat di sesi
> ini**, jadwalkan sebagai langkah terpisah sebelum mengandalkan backup otomatis.

Cron contoh (`crontab -e`, sesuaikan kredensial di atas dulu):
```
15 3 * * * cd ~/macro-engine && <perintah mysqldump di atas> && find ~/backup -mtime +14 -delete
```

## Restore

```bash
gunzip < ~/backup/macro_2026-10-11.sql.gz | mysql -h 127.0.0.1 -u root -p macro
```
Restore menimpa seluruh isi tabel yang ada di dump (bukan DROP DATABASE) — aman dijalankan ke DB
`macro` yang sudah ada strukturnya (skema dimuat dari `db/init/001_schema.sql`, bukan dari dump).

## Rotasi kunci (API_KEY, FRED/EIA/ANTHROPIC, password MySQL)

1. Edit `.env` langsung (`sed -i` atau editor), JANGAN `cat .env` ke terminal/log/chat.
2. `API_KEY`: `openssl rand -hex 32`, tempel ke `.env`, lalu `docker compose restart api scheduler`.
   Dashboard Laravel (`MACRO_ENGINE_URL` header) harus diupdate dengan key baru di saat yang sama.
3. `MYSQL_PASSWORD`: ubah di `.env` **dan** jalankan ulang bagian relevan `deploy/sudo_steps.sh`
   (step 1, `ALTER USER ... IDENTIFIED BY`) supaya password di MySQL host ikut berubah, baru restart
   `api`/`scheduler`.
4. `FRED_API_KEY`/`EIA_API_KEY`/`ANTHROPIC_API_KEY`/`TELEGRAM_*`: cukup edit `.env` + restart, tidak
   ada state di MySQL yang perlu disinkronkan.

## Update bobot faktor

1. Edit `engine/config/factors.yaml` manual (lihat `docs/CALIBRATION_<tanggal>.md` untuk rekomendasi
   berbasis data — **jangan copy `suggested_factors.yaml` tanpa membaca status per aset**: hanya aset
   dengan rekomendasi "PAKAI BOBOT FIT" yang bobotnya layak diubah).
2. `docker compose restart api scheduler` (skor dihitung ulang di jadwal berikutnya, atau paksa
   sekarang: `docker compose run --rm api python -m app.cli score`).
3. Tidak perlu migrasi DB — bobot tidak disimpan di tabel, hanya dibaca dari YAML saat runtime.

## Menambah aset atau seri baru

1. **Aset baru**: tambah entri di `engine/config/assets.yaml` (simbol Yahoo di `px`), lalu tambah
   blok faktor untuk aset itu di `engine/config/factors.yaml`.
2. **Seri FRED/EIA baru**: tambah ID di `engine/config/series.yaml` (`fred:` atau `eia:` list), isi
   `lags` bila publikasinya tidak harian (lihat `default_lags` & contoh bulanan yang sudah ada).
3. **Pasar COT baru**: tambah entri di `engine/config/cot.yaml` dengan `code` (kode kontrak CFTC) —
   **verifikasi nama pasar yang cocok** di log `ingest cot` (`docker compose run --rm api python -m
   app.cli ingest cot --full` lalu cek baris `INFO app.ingest.cot: COT <KEY> -> <NAMA>`).
4. Jalankan `docker compose run --rm api python -m app.cli backfill` untuk ingest histori aset/seri
   baru, lalu `calibrate` sebelum memakai skornya untuk keputusan nyata.

## Bila job scheduler gagal

1. Cek `job_runs` (`status != 'ok'`) dan `alerts_log` (`ok=0`) di DB untuk pesan error.
2. `docker compose logs scheduler | grep -i error` untuk traceback penuh.
3. Jalankan ulang job itu manual via CLI yang sesuai (mis. `ingest fred`, `score`, `betas`) untuk
   melihat error langsung tanpa menunggu jadwal berikutnya.
4. Job yang gagal berulang-ulang pada sumber eksternal (Yahoo rate-limit, FRED/EIA down) biasanya
   transient — scheduler akan mencoba lagi di jadwal berikutnya; selama satu sumber gagal, sumber lain
   tetap diingest (lihat desain try/except per-sumber di `app/ingest/*.py` dan `app/jobs.py`).
5. Job gagal tidak menghentikan `api` — endpoint tetap melayani data skor/harga terakhir yang berhasil
   (dengan `coverage` yang mencerminkan faktor mana yang basi/kosong).
