# Arsitektur

## Alur data

```
FRED API          EIA API v2         CFTC (zip tahunan)    Yahoo Finance       RSS bank sentral
(yield, CPI,       (stok minyak/      (posisi spekulan,     (yfinance, harga    (Fed/ECB/BoE,
 VIX, dst.)         bensin/distilat)   mingguan)             harian 16 simbol)   judul + ringkasan)
     │                   │                   │                     │                   │
     └───────────────────┴─────────┬─────────┴──────────┬──────────┴───────────────────┘
                                    ▼                    ▼
                         engine/app/ingest/*.py   (satu modul per sumber, upsert ke MySQL,
                                                    gagal per-sumber tidak menghentikan yang lain)
                                    │
                                    ▼
                      MySQL (host, DB `macro`, 13 tabel — lihat db/init/001_schema.sql)
                      macro_observations · prices_daily · cot_positions · calendar_events ·
                      headlines · headline_signals · factor_scores · bias_scores · asset_betas ·
                      scenario_runs · engine_state · job_runs · alerts_log
                                    │
                ┌───────────────────┼────────────────────────┐
                ▼                                            ▼
     app/scoring/engine.py + run.py                app/repricing/betas.py + service.py
     per aset: tiap faktor di factors.yaml         regresi mingguan aset ~ driver (HAC),
     -> transform -> z-score (lookback historis)   dekomposisi kanal (yield/breakeven/dolar),
     -> skor -2..+2 -> ×arah ×bobot -> total        deteksi rezim (korelasi minyak-S&P 26mgg lalu),
     -1..+1 + coverage + confidence                skenario (target/shock) + skenario terbalik
                │                                            │
                └──────────────────┬─────────────────────────┘
                                    ▼
                          FastAPI (app/api/main.py, 127.0.0.1:8000)
                          /health (tanpa auth) · /bias · /scenario · /meta · /calendar ·
                          /jobs/{nama} — semua selain /health butuh header X-API-Key
                                    │
                   ┌────────────────┼─────────────────────┐
                   ▼                                       ▼
        Dashboard Laravel/Livewire                  Telegram digest harian
        (host, PHP-FPM/Nginx, panggil                (app/alerts/telegram.py;
         http://127.0.0.1:8000)                       no-op bila token kosong)

app/llm/classify.py (opsional, perlu ANTHROPIC_API_KEY) memberi nada berita (-2..+2 per aset) dari
`headlines` -> ditulis ke `headline_signals` -> dibaca scoring sebagai faktor `news_tone`. Tanpa key,
faktor ini tercatat "missing" dan tidak menggagalkan skor aset lain (coverage berkurang proporsional).

app/scheduler.py (APScheduler, proses `scheduler` terpisah dari `api`) menjalankan jadwal WIB:
pipeline harian Selasa-Sabtu 06:30, COT Sabtu 08:00, EIA Rabu 23:30, berita tiap 30 menit, re-estimasi
beta Minggu 07:00. Setiap job dicatat ke `job_runs`; gagal -> `alerts_log` + Telegram (bila aktif).
```

## Topologi jaringan: container -> host.docker.internal -> MySQL host

Keputusan final proyek ini: **MySQL berjalan di host** (bukan container `mysql` bawaan
`docker-compose.yml`), supaya satu instance MySQL di VPS bisa dipakai bersama proyek lain dan tidak
ada volume Docker terpisah yang perlu dikelola/dibackup khusus untuk DB ini.

```
┌─────────────────────────────── Host (Ubuntu) ───────────────────────────────┐
│                                                                              │
│   mysqld (systemd, service `mysql`)                                        │
│   bind-address = 127.0.0.1,172.17.0.1   <- dengar di loopback DAN           │
│                                              gateway bridge docker0         │
│   DB `macro` (prod)         DB `macro_test` (sekali pakai, tes integrasi)   │
│   user macro@172.%          user macro_test@172.%  <- HANYA dari subnet    │
│   (BUKAN @'%', BUKAN root)                            172.x (docker)       │
│                                                                              │
│   docker0 (172.17.0.0/16, gw 172.17.0.1)  <- bridge DEFAULT Docker         │
│         ▲                                                                   │
│         │  host-gateway (nilai spesial extra_hosts, SELALU ke docker0      │
│         │  di Linux -- terbukti empiris, BUKAN ke network compose project) │
│         │                                                                   │
│   ┌─────┴──────────────────────────────────────────────┐                   │
│   │  network `macro-engine_default` (172.18.0.0/16)     │                   │
│   │  dibuat otomatis oleh `docker compose`               │                   │
│   │                                                       │                   │
│   │   container `api`         container `scheduler`      │                   │
│   │   172.18.0.x               172.18.0.y                 │                   │
│   │   /etc/hosts:               /etc/hosts:                │                   │
│   │   host.docker.internal      host.docker.internal       │                   │
│   │     -> 172.17.0.1             -> 172.17.0.1            │                   │
│   │   MYSQL_HOST=host.docker.internal (.env)              │                   │
│   └───────────────────────────────────────────────────────┘                   │
│                                                                              │
│   127.0.0.1:8000  <-- api (FastAPI, publikasi HANYA ke loopback)           │
│                                                                              │
└───────────────────────────────────────────────────────────────────────────┘
         ▲
         │  http://127.0.0.1:8000 (tidak pernah 0.0.0.0 — lihat deploy/VPS_UBUNTU.md)
         │
   Dashboard Laravel (proses host, di luar Docker)
```

Mekanisme kunci — **`host.docker.internal:host-gateway` di Docker/Linux selalu resolve ke gateway
bridge default `docker0`**, bukan ke gateway network compose manapun yang sedang dipakai container.
Ini ditemukan secara empiris saat setup (lihat `docs/SETUP_LOG.md` §3) setelah percobaan pertama yang
mengasumsikan sebaliknya gagal dengan `Connection refused`. Konsekuensinya: `bind-address` MySQL harus
menyertakan IP docker0 (`172.17.0.1` di mesin ini), bukan IP gateway network project
(`macro-engine_default`, `172.18.0.1`) — walau container `api`/`scheduler` berjalan DI network
`macro-engine_default`, bukan di `docker0` langsung.

Isolasi: `mysql` tidak pernah bind ke `0.0.0.0`; hanya ke loopback + satu IP privat docker0 yang tidak
pernah terhubung ke internet. User `macro`/`macro_test` dibatasi pola host `172.%` (hanya bisa
connect dari subnet docker manapun di mesin ini, tidak dari jaringan luar). `api` hanya publikasi ke
`127.0.0.1:8000`.

## Keputusan desain & alasannya

| Keputusan | Alasan |
|---|---|
| MySQL host, bukan container | Satu instance dipakai lintas proyek di VPS; hindari volume Docker terpisah untuk data yang perlu dibackup rutin. |
| User `macro`@`172.%`, bukan `%` atau root | Least privilege: hanya bisa diakses dari subnet Docker lokal, tidak dari jaringan luar; tidak pernah pakai root untuk aplikasi. |
| `depends_on: !reset {}` di api/scheduler | Compose dasar punya `depends_on: mysql (service_healthy)` lewat anchor `x-engine-env`; karena service `mysql` dinonaktifkan (profile `internal-db`), dependency itu harus dihapus total, bukan di-override sebagian. |
| `bind-address` ke docker0, bukan 0.0.0.0 | Hanya buka seperlunya (subnet Docker lokal), bukan semua interface — tetap aman walau VPS punya IP publik di interface lain. |
| `connect_args.init_command = SET time_zone='+00:00'` | Jam host/klien bisa beda (`TZ=Asia/Jakarta` di container); semua `obs_date`/`trade_date`/perhitungan point-in-time harus konsisten UTC terlepas dari itu. |
| Kalibrasi tidak pernah menimpa `factors.yaml` | Hindari overfitting diam-diam; manusia yang memutuskan kapan bobot baru layak dipakai, dengan aturan IC/p/q yang eksplisit (lihat `calibrate.py`). |
| Tes integrasi di DB terpisah (`macro_test`) | `tests/test_integration_db.py` menulis data sintetis ke tabel produksi (upsert) — tidak boleh menyentuh `macro` yang sudah berisi data nyata. |
