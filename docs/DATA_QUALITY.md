# Kualitas data setelah `backfill` pertama (2026-10-11)

Dicek: jumlah observasi, tanggal terakhir, gap > 10 hari kerja (disesuaikan per frekuensi seri:
daily > 14 hari kalender, weekly > 21 hari, monthly > 50 hari), nilai nol/negatif yang **tidak wajar**
untuk seri itu (sebagian seri seperti real yield / spread / breakeven boleh negatif secara sah), dan
lonjakan harga harian > 25%.

## Ringkasan: tidak ada seri/aset yang kosong

Semua 19 seri FRED, 3 seri EIA, 16 simbol harga (Yahoo), 8 pasar COT, dan 3 feed RSS **terisi penuh**
pada `backfill` pertama — lihat `logs/backfill_20261011.log`. Tidak ada yang perlu diulang/diperbaiki
dari sisi ingest (lihat `docs/SETUP_LOG.md` untuk detail verifikasi per sumber).

## macro_observations (FRED + EIA)

| Seri | Frekuensi | n | Tanggal terakhir | Gap terbesar | Catatan |
|---|---|---|---|---|---|
| CPIAUCSL | monthly | 199 | 2026-08-01 | 61 hari (2025-09-01 → 2025-11-01) | **Bukan bug**: shutdown pemerintah AS Okt 2025 menunda rilis BLS; data Oktober memang tidak ada di FRED. |
| CPILFESL | monthly | 199 | 2026-08-01 | 61 hari (sama) | Sama seperti di atas. |
| UNRATE | monthly | 200 | 2026-09-01 | 61 hari (sama) | Sama seperti di atas. |
| EIA_WCESTUS1 | weekly | 2297 | 2026-10-02 | 28 hari (1982-08-27 → 1982-09-24) | Keganjilan historis di awal seri (1982), 44 tahun lalu; tidak relevan untuk periode yang dipakai scoring/backtest (mulai 2014/2010). |
| EIA_WDISTUS1 | weekly | 2297 | 2026-10-02 | 28 hari (sama, 1982) | Sama. |
| EIA_WGTSTUS1 | weekly | 1918 | 2026-10-02 | 7 hari | Normal. |
| DCOILWTICO | daily | 4150 | 2026-10-06 | 8 hari | 1 nilai negatif: **2020-04-20, WTI spot FRED mencatat harga negatif** (peristiwa nyata COVID, kontrak Mei 2020 kolaps). Bukan error. |
| Semua seri lain (DGS2/10, DFII10, T5YIE/T10YIE/T10Y2Y, DTWEXBGS, VIXCLS, BAMLH0A0HYM2, DCOILBRENTEU, DFEDTARU, PAYEMS, PCEPILFE, SP500, WALCL) | - | - | - | ≤ 8 hari | Tidak ada gap/nilai tak wajar. DFII10 (955 negatif) dan T10Y2Y (544 negatif) **memang boleh negatif** (real yield & kurva terbalik) — bukan anomali. |

## prices_daily (Yahoo via yfinance)

Semua 16 simbol: gap maksimum 5 hari (akhir pekan normal), tidak ada yang "GAP" sesuai ambang.

**Lonjakan harian > 25% ditemukan (3 simbol):**

| Simbol | Tanggal | Perubahan | Penjelasan |
|---|---|---|---|
| CL=F (WTI) | 2020-04-20 s.d. 2020-04-30 | hingga +306% / harga jadi −37.63 | **Peristiwa nyata**: kontrak Mei 2020 WTI sempat settle negatif (COVID). Kontrak kontinu (`CL=F`) juga membawa efek *roll* — lihat README Keterbatasan #5. Tidak mengubah kode; sudah diketahui dan didokumentasikan. |
| SI=F (perak) | 2026-01-30 | −31% (114.04 → 78.29) | Kemungkinan besar efek *roll* kontrak kontinu, bukan kejatuhan pasar sungguhan 31% dalam sehari. Konsisten dengan keterbatasan #5 README. |
| **IDR=X (USD/IDR)** | 2010-11-01/02 **dan** 2012-02-07/08 | lompat ~10x lalu balik (mis. 8923→888→8907) | **Kemungkinan error data di sumber (Yahoo/yfinance)**, bukan peristiwa pasar — USD/IDR tidak pernah bergerak 10x dalam sehari. Dua kejadian terisolasi di riwayat lama (2010, 2012), di luar rentang `backfill_from_year`/kalibrasi COT (2014+) tetapi **masih di dalam** rentang histori harga (`history_start: 2010-01-01`) yang dipakai scoring/backtest USDIDR. |

### Keputusan yang perlu kamu ambil (lihat juga laporan akhir)
`IDR=X` punya 2 pasangan hari dengan nilai yang hampir pasti salah (bukan hasil kode kalkulasi, murni
data mentah dari Yahoo). Ini **belum diperbaiki di kode** karena di luar cakupan Langkah E (yang
mencakup COT/EIA/Yahoo-simbol/RSS, bukan validasi nilai per-hari) dan karena menambah filter
pembersihan data butuh keputusan desain (ambang apa yang dianggap "tidak masuk akal" untuk tiap
pair, berlaku untuk semua simbol atau hanya USDIDR). Dampak konkret: 4 observasi return harian ekstrem
di `USDIDR` bisa mencemari z-score (`lookback` hingga 750 hari) dan panel kalibrasi mingguan untuk
minggu-minggu yang memuat tanggal itu (2010-11, 2012-02) — out-of-sample walk-forward dimulai `train_min_years`
tahun setelah mulai data jadi dampaknya ke keputusan kalibrasi final kemungkinan kecil, tapi tetap
ada di panel CSV dan boleh diperiksa manual.

## cot_positions (CFTC)

Semua 8 pasar: 666 baris, gap maksimum 8 hari (laporan mingguan normal, tidak ada minggu yang hilang).
`net_pos` boleh negatif (short > long) — tidak diperlakukan sebagai anomali.

## headlines (RSS)

85 judul masuk (Fed 20, ECB 15, BoE 50), rentang 2026-06-22 s.d. 2026-10-09. Wajar untuk feed RSS yang
hanya menyimpan item terbaru (bukan riwayat panjang) — konsisten dengan desain `news_tone` yang memang
tidak bisa dibacktest (lihat README & `calibrate.py`).

## calendar_events

0 baris — **belum ada kalender yang diimpor** (langkah manual terpisah, lihat README § Kalender
ekonomi). Filter JANGAN ENTRY di `app/risk.py` tidak aktif sampai kalender diisi. Ini bukan kegagalan
ingest, hanya langkah operasional yang belum dilakukan.
