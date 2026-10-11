<?php

// Tambahkan ke routes/web.php.
// WAJIB di belakang autentikasi: halaman ini menampilkan keputusan trading dan mengizinkan memicu job.
// Paling cepat: `composer require laravel/breeze --dev && php artisan breeze:install blade`.

use App\Livewire\BiasBoard;
use App\Livewire\ScenarioLab;
use Illuminate\Support\Facades\Route;

Route::middleware('auth')->group(function () {
    Route::get('/', BiasBoard::class)->name('bias');
    Route::get('/scenario', ScenarioLab::class)->name('scenario');
});
