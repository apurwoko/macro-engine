# Output `score` & `scenario` (2026-10-11, setelah backfill pertama)

Contoh output pertama setelah data nyata masuk. Ini **bobot awal (prior)**, belum terkalibrasi —
lihat `docs/CALIBRATION_20261011.md` untuk hasil walk-forward dan README § "Status verifikasi".

## `python -m app.cli score`

| Aset | Bias | Total | Confidence |
|---|---|---|---|
| XAUUSD | bearish | -0.444 | 0.49 |
| XAGUSD | bearish | -0.312 | 0.30 |
| US30 | bearish | -0.550 | 0.76 |
| US100 | bearish | -0.550 | 0.76 |
| USOIL | bullish | +0.267 | 0.35 |
| UKOIL | bullish | +0.267 | 0.35 |
| EURUSD | neutral | -0.100 | 0.08 |
| GBPUSD | bearish | -0.200 | 0.16 |
| USDJPY | bullish | +0.389 | 0.67 |
| USDCAD | neutral | +0.045 | 0.03 |
| AUDUSD | bearish | -0.269 | 0.32 |
| USDIDR | bullish | +0.200 | 0.21 |

## `python -m app.cli scenario --driver oil_wti --target 93`

Baseline WTI (CL=F, 2026-10-09): **91.85** → target 93 (+1.24% log-shock). Rezim terdeteksi: **supply**.

Dampak berarti secara statistik (|t| >= 2, bukan sekadar titik estimasi):

| Target | est (%) | 80% range | t | R² | Keterangan |
|---|---|---|---|---|---|
| UKOIL (Brent) | +0.880 | [0.66, 1.10] | 5.25 | 0.65 | confidence tinggi |
| XLE (ETF energi) | +0.356 | [0.28, 0.43] | 6.17 | 0.40 | confidence tinggi |
| US30 | -0.092 | [-0.12, -0.06] | -4.01 | 0.11 | confidence sedang |
| US100 | -0.111 | [-0.18, -0.04] | -2.13 | 0.06 | confidence sedang, R² rendah |
| us2y (kanal) | +0.0074 pp | - | 3.76 | 0.10 | signifikan, efek kecil |
| bei5y (kanal) | +0.0059 pp | - | 3.79 | 0.29 | signifikan |

Aset lain (XAUUSD, XAGUSD, EURUSD, GBPUSD, USDJPY, USDCAD, AUDUSD, USDIDR, COPPER, dxy-kanal) —
**tidak signifikan** (|t| < 2) untuk shock sekecil ini (+1.24%); estimasi titik ada di output JSON
mentah tapi jangan dipakai sebagai sinyal tanpa shock yang lebih besar atau konfirmasi faktor lain.

Output mentah lengkap (semua 17 target + channel) ada di riwayat sesi deployment ini; jalankan ulang
`docker compose run --rm api python -m app.cli scenario --driver oil_wti --target 93` untuk versi
terbaru (angka bergeser setiap kali data baru masuk).
