# Dashboard Laravel (overlay)

Folder `overlay/` berisi file yang ditambahkan ke aplikasi Laravel 11/12 + Livewire 3. Dashboard hanya
menampilkan data dan meneruskan input ke API Python; tidak ada logika skor/repricing di sini.

> **Status: belum dijalankan.** File-file ini ditulis mengikuti API Livewire 3 / Laravel 11, tetapi belum
> diuji pada instalasi nyata (tidak ada PHP/Composer di lingkungan pembuatan). Yang sudah diuji adalah
> API Python yang dipanggilnya (lihat README utama). Harap uji dan koreksi bila ada yang meleset.

## Pasang

```bash
composer create-project laravel/laravel dashboard-app
cd dashboard-app
composer require livewire/livewire
composer require laravel/breeze --dev && php artisan breeze:install blade   # autentikasi (wajib, lihat bawah)

# salin file overlay (jangan menimpa routes/config; keduanya berupa snippet)
cp -R ../dashboard/overlay/app ./
cp -R ../dashboard/overlay/resources ./
```

Lalu:

1. Gabungkan `overlay/config/services.snippet.php` ke `config/services.php`.
2. Gabungkan `overlay/routes/web.snippet.php` ke `routes/web.php` (hapus route `/` bawaan).
3. Tambahkan ke `.env` aplikasi Laravel:
   ```
   MACRO_ENGINE_URL=http://127.0.0.1:8000
   MACRO_ENGINE_KEY=<sama dengan API_KEY di .env engine>
   ```
4. `php artisan migrate && php artisan serve` (atau Nginx + PHP-FPM seperti proyek Laravel lain).

## Keamanan

- API engine hanya mendengarkan `127.0.0.1:8000` (lihat `docker-compose.yml`). Jalankan Laravel di host yang sama.
  Jangan membuka port 8000 ke internet.
- Halaman ini menampilkan keputusan trading dan bisa memicu job: **lindungi dengan login**. Route snippet
  sudah memakai middleware `auth`; pastikan registrasi publik dimatikan (Breeze: hapus route register).

## Halaman

| Route | Isi |
|---|---|
| `/` | Bias per aset (skor, keyakinan, kelengkapan data), peringatan "JANGAN ENTRY" dari kalender, rincian faktor |
| `/scenario` | Pilih driver (minyak, yield 10Y, dolar, VIX), isi level target, lihat dampak per instrumen + rentang + jalur transmisi; bandingkan beberapa level; skenario terbalik |
