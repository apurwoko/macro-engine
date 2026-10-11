# Log setup & verifikasi — 2026-10-11

Kronologi deployment pertama macro-engine di mesin ini (Ubuntu, MySQL 8.0.46 sudah terpasang di host,
Docker 29.9.0 / Compose v5.6.0). Semua keputusan desain dirujuk ke prompt deployment asli (lihat
riwayat percakapan); dokumen ini fokus ke **apa yang dijalankan, apa yang gagal, dan bagaimana
diperbaiki**.

## 1. Pra-cek (Langkah A)

- MySQL `8.0.46-0ubuntu0.24.04.4` — memenuhi syarat >= 8.0.
- `ss -ltn`: hanya `127.0.0.1:3306` LISTEN sebelum perubahan; **tidak ada koneksi ESTABLISHED** ke
  3306 dan hanya satu proses `mysqld` (mulai ~08:49, bertepatan dengan setup proyek ini hari itu) ->
  disimpulkan tidak ada aplikasi lain yang bergantung pada instance ini, lanjut tanpa berhenti.
- `bind-address` awal: `127.0.0.1` (dicatat di `deploy/bind_address.rollback` sebelum diubah).
- Docker 29.9.0, Compose v5.6.0, keduanya OK. Network `macro-engine_default` (172.18.0.0/16, gw
  172.18.0.1) sudah ada dari percobaan compose sebelumnya (lihat §3).
- `.env`: FRED_API_KEY, EIA_API_KEY, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD terisi (bukan placeholder).
  **API_KEY masih placeholder `ganti_dengan_string_acak_panjang`** — lihat §6, belum diganti karena
  perintah `openssl rand` ke `.env` diblokir oleh classifier auto-mode sesi ini; perlu dilakukan manual
  atau dengan izin eksplisit.
- Tes kunci (tanpa mencetak nilai): FRED `DGS10` limit=1 -> **OK (HTTP 200)**. EIA v2
  `petroleum/stoc/wstk` seri `WCESTUS1` -> **OK (HTTP 200)** setelah menyesuaikan encoding `[]` di URL
  untuk `curl` (kode produksi di `ingest/eia.py` memakai `requests` yang sudah menangani ini otomatis,
  jadi bukan bug kode — hanya artefak cara `curl` CLI mem-parsing `[...]` sebagai glob).
- `ufw` **tidak terpasang** di mesin ini -> tidak ada aturan firewall untuk diperiksa/diubah. Isolasi
  MySQL murni dari `bind-address` + sifat privat bridge Docker (tidak terhubung ke interface publik).

## 2. Insiden keamanan: `docker compose config` mencetak `.env` plaintext

Saat validasi awal, `docker compose config` (tanpa flag) me-resolve `env_file: .env` dan mencetak
**seluruh nilai env** (termasuk `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `FRED_API_KEY`,
`EIA_API_KEY`) ke terminal/transcript. Ini melanggar aturan "jangan mencetak isi `.env`" yang
ditetapkan untuk sesi ini. **Tindak lanjut:** ditanyakan ke pengguna — pengguna memilih **lanjut pakai
kredensial yang sama** (tidak rotasi). Sejak insiden ini, validasi compose memakai
`docker compose config --no-interpolate` (menampilkan `${VAR}` mentah, tidak diresolusi) bila perlu
cek struktur lagi.

**Pelajaran untuk deployment serupa di masa depan:** jangan jalankan `docker compose config` polos di
proyek yang pakai `env_file` berisi rahasia; selalu redaksi atau pakai `--no-interpolate`.

## 3. Keputusan #3 (nonaktifkan container mysql) — dua bug ditemukan & diperbaiki

**Percobaan 1** — `docker-compose.override.yml` awal mem-pin network `default` ke subnet
`172.18.0.0/16` / gateway `172.18.0.1` (asumsi: `host.docker.internal:host-gateway` resolve ke gateway
network compose project ini). **Terbukti salah secara empiris**: `cat /etc/hosts` di dalam container
menunjukkan `host.docker.internal` resolve ke **`172.17.0.1`** (gateway bridge `docker0`, network
DEFAULT Docker), bukan ke `172.18.0.1`. Ini perilaku Docker/Linux yang terdokumentasi: nilai spesial
`host-gateway` selalu memetakan ke gateway bridge default, independen dari network custom yang dipakai
container.

**Perbaikan:**
- `docker-compose.override.yml` disederhanakan: hapus pin subnet/network (tidak relevan), sisakan
  hanya `profiles`, `depends_on: !reset {}`, dan `extra_hosts: host.docker.internal:host-gateway`
  (sesuai keputusan final, tanpa tambahan).
- `deploy/sudo_steps.sh`: `GATEWAY_IP` dihitung otomatis dari `ip -4 addr show docker0` (bukan di-hardcode),
  dan `bind-address` MySQL dibuka ke gateway **docker0**, bukan gateway network compose.

**Percobaan 2** — `mysql -u root` di dalam `sudo_steps.sh` gagal dengan
`ERROR 2005: Unknown MySQL server host 'host.docker.internal'`. Sebab: `source .env` mengekspor
`MYSQL_HOST=host.docker.internal` ke environment, dan **`mysql` CLI membaca `MYSQL_HOST`/`MYSQL_PORT`
sebagai env var resmi** — perintah admin yang seharusnya lewat socket lokal (auth_socket root) malah
mencoba TCP ke host yang tidak bisa diresolusi dari host machine. **Perbaikan:** `unset MYSQL_HOST
MYSQL_PORT MYSQL_TCP_PORT` segera setelah `source .env`, sebelum perintah admin apa pun.

**Percobaan 3** — variabel password untuk `macro_test` tertulis `TEST_DB_PASSWORD` di satu tempat tapi
dipakai sebagai `MACRO_TEST_DB_PASSWORD` di heredoc SQL -> `unbound variable` (skrip pakai `set -u`).
**Perbaikan:** satukan nama variabel jadi `MACRO_TEST_DB_PASSWORD` di semua tempat.

Setelah ketiga perbaikan, `deploy/sudo_steps.sh` dijalankan ulang (idempoten, aman) dan sukses penuh:
- DB `macro` (13 tabel — lihat §4 soal angka ini) + user `macro`@`172.%`.
- DB `macro_test` (sekali pakai) + user `macro_test`@`172.%`, kredensial di
  `deploy/.test_db_credentials` (chmod 600, di `.gitignore`, tidak pernah dicetak).
- `bind-address` -> `127.0.0.1,172.17.0.1`, MySQL restart OK.

Verifikasi akhir dari dalam container:
```
docker compose run --rm api python -c "from app import db; print(db.scalar('SELECT @@session.time_zone'))"
-> +00:00
```

## 4. Koreksi angka: skema punya 13 tabel, bukan 14

Instruksi deployment menyebut "14 baris SHOW TABLES" sebagai target verifikasi. Menghitung langsung
`CREATE TABLE` di `db/init/001_schema.sql`: **13** (`macro_observations`, `prices_daily`,
`cot_positions`, `calendar_events`, `headlines`, `headline_signals`, `factor_scores`, `bias_scores`,
`asset_betas`, `scenario_runs`, `engine_state`, `job_runs`, `alerts_log`). DB `macro` setelah load
skema: **13 tabel** — cocok persis dengan file skema, tidak ada yang hilang. Angka "14" di instruksi
awal keliru; dikoreksi di sini dan di `deploy/sudo_steps.sh`.

## 5. Build & tes (Langkah C, D)

`docker compose build` sukses (image sudah di-cache dari percobaan sebelumnya di mesin ini, build
ulang dari awal belum pernah divalidasi penuh tanpa cache sebelum sesi ini tapi tidak ada masalah
Dockerfile yang ditemukan).

Host **tidak punya** dependensi Python engine (pandas/pytest/dll) — `python3 -m pytest` di host gagal
`No module named pytest`. Ini diharapkan (dependensi hanya ada di image Docker); semua tes dijalankan
lewat `docker compose run --rm api python -m pytest ...` sesuai cara proyek ini sebenarnya dipakai.

- Unit: `docker compose run --rm api python -m pytest -q` -> **48 passed, 8 skipped** (8 skip = tes
  integrasi, perlu `MACRO_INTEGRATION_DB=1`).
- Integrasi pertama terhadap `macro_test` **gagal**: `Table 'macro_test.macro_observations' doesn't
  exist`. Sebab: komentar lama di `sudo_steps.sh` berasumsi test runner membuat skemanya sendiri —
  **salah**, `tests/test_integration_db.py` mengasumsikan tabel sudah ada (kosong). **Perbaikan**:
  tambah `mysql -u root macro_test < db/init/001_schema.sql` ke step 3 `sudo_steps.sh`.
- Setelah perbaikan, integrasi ulang: **8 passed** (termasuk `test_session_time_zone_is_utc`, tes baru
  yang ditambahkan untuk keputusan #4 — lihat `engine/tests/test_integration_db.py`).
- **Total akhir: 56 passed (48 unit + 8 integrasi), 0 gagal, 0 dilewati** (integrasi dijalankan
  terpisah dengan `MACRO_INTEGRATION_DB=1` mengarah ke `macro_test`, bukan skip).

## 6. Keputusan #4 (UTC) — kode belum ada, ditambahkan

`engine/app/db.py` sebelumnya **tidak** memaksa `time_zone` sesi. Ditambahkan
`connect_args={"init_command": "SET time_zone='+00:00'"}` di `create_engine(...)`. Tes regresi:
`test_session_time_zone_is_utc` di `tests/test_integration_db.py` (query `SELECT @@session.time_zone`,
assert `'+00:00'`). Diverifikasi lulus (§5) dan juga diverifikasi manual dari container (§3).

## 7. Backfill (Langkah E) — sukses penuh, tidak ada perbaikan kode diperlukan

Semua 4 area yang ditandai paling rawan gagal **berhasil tanpa perubahan kode** pada percobaan
pertama:
- **COT**: 8 pasar cocok dengan nama CFTC yang diharapkan (`GOLD - COMMODITY EXCHANGE INC.`, dst.),
  666 baris masing-masing, 2014-01 s.d. 2026-10.
- **EIA v2**: 3 seri (`WCESTUS1`, `WGTSTUS1`, `WDISTUS1`), 1918–2297 baris masing-masing.
- **Yahoo (yfinance)**: 16 simbol, tidak ada yang diblokir/rate-limit, semua terisi 2010–2026.
- **RSS bank sentral**: 3 feed (Fed 20, ECB 15, BoE 50 judul).

Log lengkap: `logs/backfill_20261011.log`. Tidak ada baris `ERROR`/`dilewati` di log ini. Ringkasan
per-sumber (baris, rentang tanggal, yang kosong) ada di `docs/DATA_QUALITY.md` — **tidak ada seri/aset
yang kosong**.

## 8. Kualitas data, skor, skenario, kalibrasi (Langkah F–H)

Lihat `docs/DATA_QUALITY.md` (temuan: shutdown BLS Okt 2025 -> gap CPI/UNRATE yang sah; WTI negatif
2020-04-20 -> peristiwa nyata; **dua pasangan hari dengan nilai USD/IDR yang kemungkinan salah dari
Yahoo, 2010-11 dan 2012-02, belum diperbaiki di kode -- lihat laporan akhir**),
`docs/SCORE_SCENARIO_20261011.md`, dan `docs/CALIBRATION_20261011.md` (12/12 aset berhasil
dikalibrasi, 0 dilewati, 0 aset dengan `adopt_fit=true` -- `factors.yaml` tidak berubah).

## 9. Go-live (Langkah I)

`docker compose up -d api scheduler` -> `docker compose ps` menunjukkan keduanya `Up`. `/health` ->
200 tanpa auth (sesuai desain). `/bias` dengan header `X-API-Key` (nilai dari `.env`, tidak dicetak)
-> 200, 12 item. Scheduler log menunjukkan 5 job terjadwal (`daily_pipeline`, `ingest_cot`,
`ingest_eia`, `news_cycle`, `betas`). Telegram & klasifikasi LLM **tidak aktif** (token kosong di
`.env`) — sesuai desain kode (`alerts/telegram.py` no-op bila token kosong), tidak diaktifkan secara
manual.

## Rollback / pemulihan

- **bind-address MySQL**: nilai asli `127.0.0.1` tersimpan di `deploy/bind_address.rollback`.
  Pulihkan: `sudo sed -i -E 's/^(\s*bind-address\s*=\s*).*/\1127.0.0.1/' /etc/mysql/mysql.conf.d/mysqld.cnf && sudo systemctl restart mysql`
  (atau salin dari cadangan `*.bak.<timestamp>` di direktori yang sama).
- **User DB**: `sudo mysql -u root -e "DROP USER IF EXISTS 'macro_test'@'172.%'; DROP DATABASE IF EXISTS macro_test;"`
  (lihat juga komentar di akhir `deploy/sudo_steps.sh`). User `macro`@`172.%` dan DB `macro` **tidak**
  punya skrip penghapusan otomatis (produksi) — hapus manual bila proyek dibatalkan.
- **Container**: `docker compose down` (TANPA `-v`) aman menghapus container+network, bukan data
  (data ada di MySQL host, bukan volume Docker, sejak keputusan #1).
