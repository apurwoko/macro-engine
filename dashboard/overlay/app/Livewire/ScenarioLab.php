<?php

namespace App\Livewire;

use App\Services\MacroEngine;
use Illuminate\Http\Client\RequestException;
use Livewire\Component;

class ScenarioLab extends Component
{
    // Properti numerik sengaja tanpa tipe: input kosong dari browser akan melempar TypeError pada `float`.
    public string $driver = 'oil_wti';
    public $target = 93;
    public string $regime = 'auto';
    public string $compareTargets = '85, 93, 110';
    public $reverseAsset = 'US100';
    public $reverseMove = -5;

    public array $drivers = [];
    public array $result = [];
    public array $matrix = [];
    public array $reverse = [];
    public ?string $error = null;

    public function mount(MacroEngine $engine): void
    {
        try {
            $this->drivers = $engine->meta()['drivers'] ?? [];
        } catch (\Throwable $e) {
            $this->error = $this->message($e);
        }
    }

    public function run(MacroEngine $engine): void
    {
        $this->guard(function () use ($engine) {
            $this->result = $engine->scenario([
                'driver' => $this->driver,
                'target' => (float) $this->target,
                'regime' => $this->regime,
            ]);
        });
    }

    public function compare(MacroEngine $engine): void
    {
        $targets = array_values(array_filter(
            array_map('floatval', preg_split('/[\s,;]+/', $this->compareTargets, -1, PREG_SPLIT_NO_EMPTY)),
            fn ($v) => $v > 0
        ));
        $this->guard(function () use ($engine, $targets) {
            $this->matrix = $engine->compare([
                'driver' => $this->driver,
                'targets' => $targets,
                'regime' => $this->regime,
            ]);
        });
    }

    public function reverseRun(MacroEngine $engine): void
    {
        $this->guard(function () use ($engine) {
            $this->reverse = $engine->reverse([
                'driver' => $this->driver,
                'asset' => strtoupper((string) $this->reverseAsset),
                'move_pct' => (float) $this->reverseMove,
            ]);
        });
    }

    private function guard(callable $fn): void
    {
        $this->error = null;
        try {
            $fn();
        } catch (\Throwable $e) {
            $this->error = $this->message($e);
        }
    }

    private function message(\Throwable $e): string
    {
        if ($e instanceof RequestException) {
            $detail = $e->response->json('detail');
            return is_array($detail) ? json_encode($detail, JSON_UNESCAPED_UNICODE) : ($detail ?: $e->getMessage());
        }
        return $e->getMessage();
    }

    public function render()
    {
        return view('livewire.scenario-lab');
    }
}
