# Kalibrasi walk-forward — 2026-10-11 (data nyata pertama)

Laporan lengkap (per aset `.md`, `panel_<ASET>.csv`, `suggested_factors.yaml`) ada di
`reports/calibration_20261011_0457/`. **`engine/config/factors.yaml` TIDAK diubah** oleh perintah ini —
`suggested_factors.yaml` di folder itu hanyalah usulan, dan di jalankan ini usulannya identik dengan
bobot awal karena tidak ada aset yang lolos aturan adopsi (lihat di bawah).

Parameter: `start=2014-01-01`, `horizon=28` hari, `lam=1.0`, `train_min_years=3` (default CLI).

## ⚠️ Cara membaca tabel ini — WAJIB dibaca sebelum lanjut

**"TIDAK ADA BUKTI" berarti data saat ini (≈667 minggu, 510 minggu out-of-sample per aset) tidak cukup
untuk MEMBUKTIKAN atau MEMBANTAH nilai prediktif skor bias — bukan bukti bahwa faktornya tidak
berguna.** Dari README: dengan ~12 tahun data, sinyal selemah IC 0.09 hanya terdeteksi ~25% dari waktu.
Semua 12 aset di bawah jatuh ke kategori ini pada run pertama ini. **Jangan menyimpulkan "bobotnya
salah" dari tabel ini** — simpulkan "belum ada cukup bukti untuk menilai", dan pertahankan bobot awal
(sudah berjalan secara default, karena tidak ada `adopt_fit`).

## Ringkasan (12/12 aset berhasil dikalibrasi, 0 DILEWATI)

| Aset | n_oos (minggu) | IC prior | p prior | q prior | IC fit | p fit | q fit | IC momentum | Status | Rekomendasi |
|---|---|---|---|---|---|---|---|---|---|---|
| XAUUSD | 510 | +0.007 | 0.942 | 0.994 | -0.039 | 0.663 | 0.996 | +0.036 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| XAGUSD | 510 | -0.002 | 0.981 | 0.994 | +0.032 | 0.719 | 0.996 | -0.013 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| US30 | 510 | -0.019 | 0.836 | 0.994 | -0.006 | 0.949 | 0.996 | -0.159 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| US100 | 510 | +0.022 | 0.804 | 0.994 | -0.011 | 0.907 | 0.996 | -0.082 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| USOIL | 510 | +0.018 | 0.842 | 0.994 | -0.000 | 0.996 | 0.996 | -0.016 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| UKOIL | 510 | -0.002 | 0.978 | 0.994 | +0.001 | 0.989 | 0.996 | +0.023 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| EURUSD | 510 | +0.022 | 0.809 | 0.994 | +0.020 | 0.823 | 0.996 | +0.020 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| GBPUSD | 510 | +0.064 | 0.476 | 0.994 | +0.029 | 0.748 | 0.996 | -0.050 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| USDJPY | 510 | +0.010 | 0.910 | 0.994 | -0.062 | 0.492 | 0.996 | -0.035 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| USDCAD | 510 | -0.001 | 0.994 | 0.994 | +0.062 | 0.489 | 0.996 | -0.113 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| AUDUSD | 510 | -0.040 | 0.659 | 0.994 | -0.018 | 0.839 | 0.996 | -0.060 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |
| USDIDR | 510 | -0.011 | 0.904 | 0.994 | +0.035 | 0.693 | 0.996 | -0.015 | TIDAK ADA BUKTI | Jangan andalkan bias aset ini |

Tidak ada `adopt_fit=true` di manapun -> `suggested_factors.yaml` identik dengan `factors.yaml` saat ini.
Tidak ada aset dengan status TERKONFIRMASI/KANDIDAT -> tidak ada yang perlu "dipertahankan secara eksplisit
karena terbukti", semuanya berstatus data-tidak-cukup.

## Yang MENONJOL (bukan kesimpulan, sekadar observasi untuk dipantau)

- **GBPUSD** punya IC prior tertinggi (+0.064, p=0.48) di antara semua aset — masih jauh dari ambang
  signifikan (p<0.10), tapi aset dengan prior IC positif tertinggi di sampel ini.
- **US30 dan USDCAD** punya IC prior negatif kecil (-0.019, -0.001) — sejalan dengan README yang sudah
  mencurigai US30 "kurang sensitif ke yield riil" dibanding US100 (keduanya memakai faktor yang sama).
  Ini masih deskriptif (p tidak signifikan), bukan bukti arah faktor salah.
- Semua `q_prior` dan `q_fit` berada di 0.994–0.996 — mengonfirmasi bahwa setelah koreksi
  Benjamini-Hochberg lintas 12 aset, **tidak ada yang lolos** sebagai temuan nyata, konsisten dengan
  p-value individual yang juga semuanya tinggi.
- IC momentum (pembanding sederhana, tanpa faktor fundamental apa pun) juga kecil dan tidak konsisten
  tandanya antar aset — menunjukkan periode ini secara umum sulit diprediksi dengan metode sederhana
  apa pun, bukan hanya model fundamental ini.

## Implikasi praktis

Dengan data yang ada sekarang, **tetap pakai bobot awal `factors.yaml`** (keputusan default — tidak ada
yang di-adopt). Jangan menaikkan/menurunkan bobot berdasarkan hasil ini. Opsi lanjutan dari README:
pooling aset sejenis (US30+US100) atau horizon lebih panjang, untuk menambah daya statistik — belum
dilakukan di sesi ini (di luar cakupan tugas).
