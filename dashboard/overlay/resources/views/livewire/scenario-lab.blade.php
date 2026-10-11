<div>
    @if ($error)<div class="alert">{{ $error }}</div>@endif

    <h2 style="margin-top:0">Skenario: "jika harga X, apa dampaknya?"</h2>

    <div class="card">
        <div class="row">
            <label>Driver
                <select wire:model.live="driver">
                    @foreach ($drivers as $key => $d)
                        <option value="{{ $key }}">{{ $d['label'] }} ({{ $d['unit'] }})</option>
                    @endforeach
                </select>
            </label>
            <label>Level target
                <input type="number" step="any" wire:model="target" style="width:120px">
            </label>
            <label>Rezim
                <select wire:model="regime">
                    <option value="auto">auto (deteksi)</option>
                    <option value="supply">supply shock</option>
                    <option value="demand">demand shock</option>
                    <option value="all">semua (rata-rata)</option>
                </select>
            </label>
            <button wire:click="run">Hitung</button>
        </div>
    </div>

    @if ($result)
        <div class="card">
            <strong>{{ $result['driver_label'] ?? $result['driver'] }}:</strong>
            {{ number_format($result['baseline'], 2) }} → {{ number_format($result['target'], 2) }} {{ $result['unit'] ?? '' }}
            <small>(rezim dipakai: {{ $result['regime_applied'] }}, rezim terdeteksi: {{ $result['regime_current'] ?? 'n/a' }})</small>
            @foreach ($result['warnings'] as $w)<div class="warn">⚠ {{ $w }}</div>@endforeach
        </div>

        <table>
            <thead><tr><th>Instrumen</th><th>Estimasi</th><th>Rentang 80%**</th><th>Keyakinan</th><th>Jalur utama</th><th>Catatan</th></tr></thead>
            <tbody>
            @foreach ($result['results'] as $r)
                @php
                    $cls = $r['est'] > 0 ? 'up' : ($r['est'] < 0 ? 'down' : 'mut');
                    $ch = collect($r['channels'] ?? [])->except('unexplained')->sortByDesc(fn ($v) => abs($v))->take(2);
                @endphp
                <tr>
                    <td>{{ $r['name'] }} @if ($r['role'] === 'channel')<span class="badge">kanal</span>@endif</td>
                    <td class="{{ $cls }}"><strong>{{ sprintf('%+.2f', $r['est']) }}{{ $r['unit'] }}</strong></td>
                    <td class="mut">{{ sprintf('%+.2f', $r['lo']) }} … {{ sprintf('%+.2f', $r['hi']) }}</td>
                    <td>{{ $r['confidence'] }} <small>(t={{ number_format($r['t'], 1) }}, R²={{ number_format($r['r2'], 2) }})</small></td>
                    <td><small>@foreach ($ch as $k => $v){{ $k }} {{ sprintf('%+.1f', $v) }}{{ $r['unit'] }}@if (!$loop->last), @endif @endforeach</small></td>
                    <td><small class="warn">{{ implode('; ', $r['flags']) }}</small></td>
                </tr>
            @endforeach
            </tbody>
        </table>
        <p><small>
            **Rentang hanya ketidakpastian estimasi beta, bukan noise harga (deviasi mingguan tipikal ada di API: <code>noise_1w</code>).
            @foreach ($result['notes'] as $n)<br>{{ $n }}@endforeach
        </small></p>
    @endif

    <div class="card" style="margin-top:20px">
        <div class="row">
            <label>Bandingkan beberapa level (pisah koma)
                <input type="text" wire:model="compareTargets" style="width:220px">
            </label>
            <button wire:click="compare">Bandingkan</button>
        </div>
    </div>

    @if ($matrix)
        <table>
            <thead><tr><th>Instrumen</th>@foreach ($matrix['targets'] as $t)<th>{{ $t }}</th>@endforeach</tr></thead>
            <tbody>
            @foreach ($matrix['matrix'] as $code => $m)
                <tr>
                    <td>{{ $m['name'] }}</td>
                    @foreach ($m['est'] as $i => $v)
                        <td class="{{ $v > 0 ? 'up' : ($v < 0 ? 'down' : 'mut') }}">{{ sprintf('%+.2f', $v) }}{{ $m['unit'] }} <small>({{ $m['conf'][$i] }})</small></td>
                    @endforeach
                </tr>
            @endforeach
            </tbody>
        </table>
    @endif

    <div class="card" style="margin-top:20px">
        <strong>Skenario terbalik:</strong>
        <div class="row" style="margin-top:8px">
            <label>Jika aset
                <input type="text" wire:model="reverseAsset" style="width:100px">
            </label>
            <label>bergerak (%)
                <input type="number" step="any" wire:model="reverseMove" style="width:100px">
            </label>
            <button wire:click="reverseRun">Apa yang konsisten untuk driver?</button>
        </div>
        @if ($reverse)
            <p>
                Driver ({{ $reverse['driver'] }}) yang konsisten secara historis: <strong>{{ sprintf('%+.2f', $reverse['implied']) }}{{ $reverse['unit'] }}</strong>
                <small>(R²={{ number_format($reverse['r2'], 2) }}, n={{ $reverse['n'] }})</small>
                @foreach ($reverse['warnings'] as $w)<br><span class="warn">⚠ {{ $w }}</span>@endforeach
            </p>
        @endif
    </div>
</div>
