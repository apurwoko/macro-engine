<?php

namespace App\Livewire;

use App\Services\MacroEngine;
use Livewire\Component;

class BiasBoard extends Component
{
    public array $items = [];
    public ?string $error = null;
    public ?string $notice = null;
    public ?string $open = null;       // aset yang detail faktornya sedang dibuka
    public array $details = [];

    public function mount(MacroEngine $engine): void
    {
        $this->load($engine);
    }

    public function load(MacroEngine $engine): void
    {
        try {
            $this->items = $engine->bias();
            $this->error = null;
        } catch (\Throwable $e) {
            $this->error = 'Engine tidak terjangkau: '.$e->getMessage();
        }
    }

    public function toggle(string $asset, MacroEngine $engine): void
    {
        if ($this->open === $asset) {
            $this->open = null;
            return;
        }
        try {
            $this->details = $engine->biasDetail($asset)['details'] ?? [];
            $this->open = $asset;
        } catch (\Throwable $e) {
            $this->error = $e->getMessage();
        }
    }

    public function refresh(MacroEngine $engine): void
    {
        try {
            $engine->runJob('daily_pipeline');
            $this->notice = 'Pipeline dimulai di latar belakang. Muat ulang halaman setelah beberapa menit.';
        } catch (\Throwable $e) {
            $this->error = $e->getMessage();
        }
    }

    public function render()
    {
        return view('livewire.bias-board');
    }
}
