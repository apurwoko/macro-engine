<?php

namespace App\Services;

use Illuminate\Http\Client\PendingRequest;
use Illuminate\Support\Facades\Http;

/**
 * Klien tipis untuk API Python (FastAPI). Semua logika skor/repricing ada di sisi Python;
 * Laravel hanya menampilkan dan meneruskan input.
 */
class MacroEngine
{
    private function http(): PendingRequest
    {
        return Http::baseUrl(rtrim((string) config('services.macro_engine.url'), '/'))
            ->withHeaders(['X-API-Key' => (string) config('services.macro_engine.key')])
            ->acceptJson()
            ->timeout(60);
    }

    public function meta(): array
    {
        return $this->http()->get('/meta')->throw()->json() ?? [];
    }

    /** @return array<int, array<string, mixed>> */
    public function bias(): array
    {
        return $this->http()->get('/bias')->throw()->json('items') ?? [];
    }

    public function biasDetail(string $asset): array
    {
        return $this->http()->get('/bias/'.urlencode($asset))->throw()->json() ?? [];
    }

    public function scenario(array $payload): array
    {
        return $this->http()->post('/scenario', $payload)->throw()->json() ?? [];
    }

    public function compare(array $payload): array
    {
        return $this->http()->post('/scenario/compare', $payload)->throw()->json() ?? [];
    }

    public function reverse(array $payload): array
    {
        return $this->http()->post('/scenario/reverse', $payload)->throw()->json() ?? [];
    }

    public function runJob(string $name): void
    {
        $this->http()->post('/jobs/'.urlencode($name))->throw();
    }
}
