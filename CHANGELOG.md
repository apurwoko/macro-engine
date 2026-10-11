# Changelog

## 2026-10-11 — Deployment pertama di mesin nyata (MySQL host, bukan container)

### Kode

- **`engine/app/db.py`** — tambah `connect_args={"init_command": "SET time_zone='+00:00'"}` ke
  `create_engine(...)`. Alasan: keputusan #4 deployment (semua sesi DB harus UTC terlepas dari
  `TZ` host/klien); kode sebelumnya tidak memaksa ini sama sekali.
  Tes: `test_session_time_zone_is_utc` (baru, lihat di bawah) + verifikasi manual
  (`SELECT @@session.time_zone` dari dalam container -> `+00:00`, dicatat di `docs/SETUP_LOG.md` §6).

- **`engine/tests/test_integration_db.py`** — tambah `test_session_time_zone_is_utc`: query
  `SELECT @@session.time_zone`, assert `'+00:00'`. Regresi untuk perubahan `db.py` di atas.

### Infrastruktur deployment (baru)

- **`docker-compose.override.yml`** — nonaktifkan service `mysql` bawaan (`profiles:
  ["internal-db"]`), hapus `depends_on` ke `mysql` di `api`/`scheduler` (`!reset {}`), tambah
  `extra_hosts: host.docker.internal:host-gateway`. Alasan: keputusan #1/#3 (pakai MySQL host yang
  sudah ada, bukan container). Diverifikasi: `docker compose config` (service `mysql` tidak muncul),
  koneksi `api`→MySQL host berhasil (lihat `docs/SETUP_LOG.md` §3).

- **`deploy/sudo_steps.sh`** — skrip tunggal untuk semua langkah sudo: buat DB `macro` + user
  `macro`@`172.%`, muat `db/init/001_schema.sql`, buat DB `macro_test` + user sekali pakai untuk tes
  integrasi (muat skema juga), buka `bind-address` MySQL ke gateway `docker0` (dideteksi otomatis via
  `ip -4 addr show docker0`, bukan di-hardcode). Idempoten (aman dijalankan ulang). Alasan: keputusan
  #2/#3 + aturan "kumpulkan sudo jadi satu skrip". Diverifikasi: dijalankan 4x selama setup (2x
  menemukan bug di skrip sendiri — lihat `docs/SETUP_LOG.md` §3 — diperbaiki, lalu sukses penuh;
  hasil akhir: 13 tabel di `macro`, user `macro`/`macro_test` aktif, `bind-address` benar).

### Konfigurasi (bukan kode, dicatat untuk kelengkapan — nilai TIDAK dicetak di sini)

- **`.env`**: `MYSQL_HOST` -> `host.docker.internal`, `MYSQL_PORT` -> `3306` (eksplisit). Alasan:
  keputusan #3.
- **`.gitignore`**: tambah `logs/`, `deploy/.test_db_credentials`, `deploy/bind_address.rollback` —
  file-file ini berisi kredensial/state lokal, tidak boleh ikut commit.

### Dokumentasi (baru/diperbarui)

- `docs/SETUP_LOG.md`, `docs/ARCHITECTURE.md`, `docs/RUNBOOK.md`, `docs/DATA_QUALITY.md`,
  `docs/CALIBRATION_20261011.md`, `docs/SCORE_SCENARIO_20261011.md` — baru, lihat isinya masing-masing.
- `README.md` — bagian "Mulai cepat" (dua jalur MySQL), "Status verifikasi" (diperbarui dengan hasil
  verifikasi nyata), tambah temuan USD/IDR ke "Keterbatasan", tambah bagian "Dokumentasi".
- `deploy/VPS_UBUNTU.md` — bagian baru "1b. Memakai MySQL yang sudah ada", penyesuaian §3 (lewati
  `docker compose up -d mysql` bila pakai §1b) dan §4 (backup untuk MySQL host sendiri).

### Tidak diubah (sengaja)

- `engine/config/factors.yaml` — **tidak disentuh** (keputusan #5; hasil `calibrate` tidak ada yang
  memenuhi aturan adopsi, lihat `docs/CALIBRATION_20261011.md`).
- `db/init/001_schema.sql` — tidak ada perubahan skema; 13 tabel sudah sesuai kebutuhan saat ingest
  nyata pertama.
- `engine/app/ingest/*.py` — tidak ada perubahan; semua 4 sumber yang ditandai rawan gagal (COT, EIA,
  Yahoo, RSS) berhasil tanpa modifikasi kode pada `backfill` pertama (lihat `docs/SETUP_LOG.md` §7).

### Diketahui, belum diperbaiki (keputusan terbuka)

- `API_KEY` di `.env` masih nilai placeholder dari `.env.example` — perintah untuk menggantinya
  dengan nilai acak diblokir oleh classifier auto-mode sesi ini; perlu dilakukan manual atau dengan
  izin eksplisit (lihat `docs/SETUP_LOG.md` §1).
- 2 pasang hari dengan nilai `IDR=X` (USD/IDR) yang kemungkinan salah dari Yahoo (2010-11-01/02,
  2012-02-07/08) — lihat `docs/DATA_QUALITY.md`. Belum ada filter/koreksi di `ingest/prices.py`.
