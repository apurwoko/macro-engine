# Macro Engine

Sistem bias fundamental + repricing untuk forex, emas, perak, US30, US100, dan minyak.

- **Bias harian** per aset: skor -1..+1, keyakinan, kelengkapan data, dan peringatan **JANGAN ENTRY** menjelang rilis besar.
- **Repricing**: "jika minyak ke 93, apa dampaknya ke emas, US100, USD/CAD, USD/IDR, dst." lengkap dengan jalur transmisi
  (yield 2Y, breakeven inflasi, dolar), rentang ketidakpastian, rezim supply/demand shock, dan skenario terbalik.
- Dipakai sebagai **filter arah** bagi sistem teknikalmu (CHoCH/EMA/pivot), bukan sinyal entry.

```
FRED / EIA / CFTC / Yahoo / RSS ──► ingest (Python) ──► MySQL
                                                          │
                          ┌───────────────────────────────┤
                          ▼                               ▼
                scoring (faktor → z-score)        repricing (beta mingguan,
                + LLM nada berita (Claude)        HAC, rezim, dekomposisi kanal)
                          └───────────────┬───────────────┘
                                          ▼
                              FastAPI (127.0.0.1:8000)
                                 │                │
                          Laravel/Livewire     Telegram digest
                           (dashboard)         (harian + alert job gagal)
```

## Struktur

```
docker-compose.yml        mysql + api + scheduler
db/init/001_schema.sql    skema MySQL (otomatis dimuat saat volume pertama dibuat)
engine/
  config/                 assets, series, factors (bobot), cot, feeds  ← yang paling sering kamu edit
  app/ingest/             fred, prices, cot, eia, news, calendar
  app/scoring/            engine.py (murni) + run.py (DB)
  app/repricing/          betas.py, scenario.py (murni) + service.py (DB) + variables.py
  app/llm/classify.py     klasifikasi headline (output terstruktur, divalidasi)
  app/risk.py             filter kalender/blackout
  app/api/main.py         endpoint untuk Laravel
  app/scheduler.py        jadwal otomatis (WIB)
  app/backtest.py         uji nilai prediktif skor
  tests/                  unit + integrasi
dashboard/overlay/        file Laravel/Livewire (lihat dashboard/README.md)
```

## Mulai cepat

Dua jalur MySQL — pilih satu:

**A. Container `mysql` bawaan** (volume Docker terpisah untuk DB ini):
```bash
cp .env.example .env            # isi password MySQL, FRED_API_KEY, EIA_API_KEY, API_KEY (acak panjang)
docker compose up -d mysql
docker compose build
docker compose run --rm api python -m app.cli backfill      # unduh riwayat, hitung beta, skor pertama
docker compose up -d api scheduler
curl -H "X-API-Key: <API_KEY>" http://127.0.0.1:8000/bias
```

**B. MySQL yang sudah terpasang di host** (satu instance dipakai lintas proyek) — diverifikasi
end-to-end di `docs/SETUP_LOG.md`:
```bash
cp .env.example .env            # MYSQL_HOST=host.docker.internal, isi FRED_API_KEY, EIA_API_KEY, API_KEY
# docker-compose.override.yml menonaktifkan service mysql + extra_hosts host.docker.internal
#   (lihat deploy/VPS_UBUNTU.md § "Memakai MySQL yang sudah ada" untuk isi filenya)
sudo bash deploy/sudo_steps.sh   # buat DB `macro` + user macro@172.%, muat skema, buka bind-address
docker compose build
docker compose run --rm api python -m app.cli backfill
docker compose up -d api scheduler
curl -H "X-API-Key: <API_KEY>" http://127.0.0.1:8000/bias
```
Detail arsitektur jalur B (kenapa `host.docker.internal` resolve ke gateway `docker0`, bukan gateway
network compose) ada di `docs/ARCHITECTURE.md`. Operasional harian (backup, restore, rotasi kunci,
job gagal): `docs/RUNBOOK.md`.

Kunci gratis: FRED <https://fred.stlouisfed.org/docs/api/api_key.html>, EIA <https://www.eia.gov/opendata/register.php>.
Tanpa `ANTHROPIC_API_KEY` klasifikasi berita dilewati (faktor `news_tone` tercatat "missing", sisanya tetap jalan).

**Cek log `backfill` untuk baris COT**: tiap pasar mencetak nama pasar CFTC yang cocok (mis. `GOLD - COMMODITY EXCHANGE INC.`).
Pastikan namanya sesuai; bila tidak, perbaiki kode kontrak di `engine/config/cot.yaml`.

Kalender ekonomi: isi CSV (`engine/data/calendar_template.csv`) lalu `docker compose run --rm -v "$PWD/mydata:/data" api python -m app.cli calendar /data/kalender.csv`
(format kolom di docstring `app/ingest/calendar.py`; waktu dalam UTC). Tanpa kalender, filter JANGAN ENTRY tidak aktif.

## Perintah

```
python -m app.cli ingest {fred,prices,cot,eia,news} [--full]
python -m app.cli score | betas | classify | digest | backfill
python -m app.cli scenario --driver oil_wti --target 93
python -m app.cli backtest XAUUSD --start 2014-01-01
python -m app.cli calibrate [ASET ...] [--horizon 28] [--lam 1.0]   # laporan di reports/
python -m app.cli calendar kalender.csv
```

Tes: `cd engine && python -m pytest -q` (unit). Integrasi DB (pakai **database kosong sekali pakai**):
`MACRO_INTEGRATION_DB=1 MYSQL_HOST=... python -m pytest tests/test_integration_db.py`.

## Cara kerja singkat

**Skor bias** (`config/factors.yaml`): tiap faktor → transform (selisih/persen/level) → z-score terhadap riwayatnya
→ skor -2..+2 → × arah → × bobot. Data basi dikeluarkan; `coverage` menunjukkan porsi bobot yang datanya ada.
Seri makro memakai **jeda publikasi** (`series.yaml: lags`) agar tidak mengintip masa depan. LLM hanya memberi nada berita
(-2..+2 per aset); skor akhir dihitung di kode.

**Repricing**: regresi mingguan `aset ~ driver` dengan galat standar HAC. Dekomposisi kanal memakai identitas
`beta total = efek langsung + Σ (efek kanal × sensitivitas kanal terhadap driver)`, yang eksak dalam sampel (diuji).
Rezim (supply/demand) ditentukan dari korelasi minyak-S&P 26 minggu **sebelumnya**, bukan hasil minggu yang diregresi.
Rentang 80% hanya mencerminkan ketidakpastian beta. Skenario terbalik memakai regresi balik (bukan 1/beta).

**Jadwal (WIB)**: pipeline harian Selasa-Sabtu 06:30 (ingest → skor → Telegram), COT Sabtu 08:00, stok EIA Rabu 23:30,
berita tiap 30 menit, re-estimasi beta Minggu 07:00. Job gagal dikirim ke Telegram dan dicatat di `job_runs`.

## Kalibrasi bobot & backtest per aset

`python -m app.cli calibrate` (setelah `backfill`) menulis `reports/calibration_<waktu>/`: `summary.csv`, `<ASET>.md`,
`panel_<ASET>.csv`, `suggested_factors.yaml`. **Tidak pernah menimpa `factors.yaml`**; kamu yang memutuskan menyalin usulan.

Metode: target = return ke depan (default 28 hari) dinormalisasi volatilitas; bobot dicocokkan dengan NNLS (bobot >= 0, jadi
data tidak bisa membalik logika arah ekonomi) dengan shrinkage ridge ke bobot awal; evaluasi **walk-forward per tahun
kalender** dengan embargo sepanjang horizon; metrik = IC Spearman out-of-sample, p-value memakai n efektif (sampel tumpang-tindih),
q-value Benjamini-Hochberg lintas aset; pembanding = momentum sederhana.

Aturan keputusan: bobot hasil fit dipakai hanya bila IC_fit - IC_prior >= 0.02, IC_fit > 0, dan p_fit < 0.10.
Status: TERKONFIRMASI (lolos q), KANDIDAT (lolos p tetapi tidak q), TIDAK ADA BUKTI.

**Cara membaca (penting).** Uji sintetis menunjukkan dengan ~12 tahun data, sinyal selemah IC 0.09 hanya terdeteksi ~25% dari waktu,
sedangkan dengan sinyal nol, bobot fit dipilih 0 dari 16 percobaan. Jadi "TIDAK ADA BUKTI" sering berarti *data tidak cukup untuk
memutuskan*, bukan *faktor tidak berguna*. Gunakan alat ini untuk menangkap **tanda salah dan faktor redundan**, bukan untuk
membuktikan edge. Bobot awal yang tidak terbukti salah sebaiknya dipertahankan. Faktor `news_tone` dikecualikan (tak ada riwayat).
Ide lanjutan bila bukti terlalu tipis per aset: pooling aset sejenis (mis. US30+US100), horizon lebih panjang.

## Status verifikasi (jujur)

Diperbarui 2026-10-11 setelah deployment pertama di mesin nyata (Ubuntu, MySQL 8.0.46 host, Docker
29.9.0). Kronologi lengkap (termasuk 2 bug yang ditemukan & diperbaiki saat setup): `docs/SETUP_LOG.md`.

| Bagian | Status |
|---|---|
| Logika skor, beta, dekomposisi, skenario, risiko event, parser COT/kalender, sanitasi LLM, jadwal | **Diuji** (unit, data sintetis) — 48 test, lihat `engine/tests/` |
| Skema + upsert + seluruh query + API end-to-end | **Diuji di MySQL 8.0.46 sungguhan** (bukan lagi hanya MariaDB) dengan data sintetis di DB sekali pakai — 8 test integrasi, 56 total lulus. Cara: `docs/RUNBOOK.md` / README § Tes |
| `connect_args` UTC (`SET time_zone='+00:00'`) | **Diuji**: `test_session_time_zone_is_utc` + verifikasi manual dari container |
| Alat kalibrasi (walk-forward, embargo, tanpa look-ahead, deteksi/pembuangan faktor berarah salah) | Diuji pada dunia sintetis **dan** dijalankan pada **data pasar nyata** (2026-10-11, 12/12 aset, 0 dilewati). Hasil: **semua 12 aset "TIDAK ADA BUKTI"** (data historis saat ini belum cukup untuk membuktikan/membantah skor) — lihat `docs/CALIBRATION_20261011.md`. Bobot awal `factors.yaml` dipertahankan, tidak ada yang diubah. |
| Pola URL arsip CFTC | **Dikonfirmasi** dari halaman CFTC, dan **dikonfirmasi lagi** dari unduhan nyata saat `backfill` (8/8 pasar cocok) |
| Nama kolom & kode kontrak COT, route EIA v2, simbol Yahoo, feed RSS bank sentral | **Diverifikasi dari unduhan nyata** (2026-10-11): semua 8 pasar COT, 3 seri EIA, 16 simbol Yahoo, 3 feed RSS berhasil tanpa perubahan kode. Detail: `docs/DATA_QUALITY.md`, log: `logs/backfill_20261011.log` |
| Panggilan nyata ke FRED, EIA, Yahoo | **Dijalankan dan berhasil** (lihat baris di atas). Telegram & Claude API: **belum diaktifkan** (kunci sengaja kosong di deployment ini, lihat `docs/SETUP_LOG.md` §9) |
| `docker compose build/up` | **Dijalankan dan berhasil** di mesin nyata; `api`+`scheduler` up, `/health` dan `/bias` terverifikasi |
| Kualitas data mentah | Satu temuan terbuka: 2 pasang hari dengan nilai USD/IDR yang kemungkinan salah dari Yahoo (2010-11, 2012-02) — **belum diperbaiki di kode**, lihat `docs/DATA_QUALITY.md` § Keputusan yang perlu diambil |
| Dashboard Laravel/Livewire | Sintaks PHP dilint; Blade & alur **belum dijalankan** |

## Keterbatasan yang perlu kamu putuskan sebelum memercayai output

1. **Bobot faktor adalah tebakan berbasis logika makro, belum terkalibrasi.** Jalankan `backtest` per aset (IC Spearman,
   hit-rate) sebelum dipakai. Pada data sintetis tanpa hubungan prediktif, harness ini melaporkan IC ≈ 0 dengan p tinggi
   (artinya tidak membocorkan masa depan); pada data nyata, jangan men-tune bobot berlebihan terhadap hasilnya
   (overfitting). Sampel mingguan dengan horizon 4 minggu saling tumpang-tindih.
2. **Keyakinan** adalah heuristik, bukan probabilitas.
3. Data revisi (CPI dll.) tampil dalam versi akhir di backtest; jeda publikasi bulanan hanya pendekatan kasar.
4. Stok minyak EIA sangat musiman; z-score saat ini belum membuang musiman.
5. Yahoo (`yfinance`) tidak resmi dan kontrak kontinu punya efek roll; untuk produksi ganti ke feed broker/MT5
   (paket `MetaTrader5` hanya jalan di Windows, jadi ingest-nya dijalankan di mesin Windows, bukan di container).
6. USD/IDR belum memuat faktor domestik (BI rate, neraca dagang, arus asing); keyakinannya rendah.
7. Beta linier: shock di luar rentang historis diberi peringatan ekstrapolasi. Bila level skenario sudah tercermin di
   kurva futures, sisa repricing lebih kecil dari estimasi.
8. Tidak ada jaminan hasil. Uji di demo/lot kecil dulu.
9. **Ditemukan saat `backfill` 2026-10-11**: harga `IDR=X` (USD/IDR) dari Yahoo punya 2 pasang hari
   dengan nilai yang hampir pasti salah (lompat ~10x lalu balik, 2010-11 dan 2012-02) — kemungkinan
   besar error data di sumber, bukan hasil kode. Belum difilter/diperbaiki. Detail & dampak:
   `docs/DATA_QUALITY.md`.

## Dokumentasi

- `docs/SETUP_LOG.md` — kronologi setup pertama di mesin nyata: apa yang dijalankan, bug yang
  ditemukan & diperbaiki, cara rollback.
- `docs/ARCHITECTURE.md` — diagram alur data, topologi jaringan (container ↔ MySQL host), keputusan
  desain & alasannya.
- `docs/RUNBOOK.md` — operasi harian: start/stop, log, backup/restore, rotasi kunci, tambah
  aset/seri, job gagal.
- `docs/DATA_QUALITY.md` — hasil cek kualitas data setelah `backfill` pertama (gap, nilai tak wajar,
  lonjakan harga).
- `docs/CALIBRATION_20261011.md` — hasil `calibrate` pertama pada data pasar nyata, per aset.
- `docs/SCORE_SCENARIO_20261011.md` — contoh output `score`/`scenario` pertama.
- `CHANGELOG.md` — perubahan kode dari sesi deployment ini (file, alasan, tes).

## Langkah berikutnya yang disarankan

1. `backfill` → cek log COT & nama pasar → isi kalender → `calibrate` (panduan server: deploy/VPS_UBUNTU.md).
2. Pasang dashboard (dashboard/README.md).
3. Setelah kalibrasi: pangkas faktor yang tidak berkontribusi, hilangkan musiman stok EIA, tambah faktor domestik USD/IDR.
4. Putuskan soal 2 pasang hari `IDR=X` yang kemungkinan salah (`docs/DATA_QUALITY.md`) dan API_KEY
   yang masih placeholder (`docs/SETUP_LOG.md` §1) sebelum go-live sungguhan.
