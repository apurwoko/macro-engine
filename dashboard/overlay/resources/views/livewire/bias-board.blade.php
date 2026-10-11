<div>
    @if ($error)<div class="alert">{{ $error }}</div>@endif
    @if ($notice)<div class="alert">{{ $notice }}</div>@endif

    <div class="row" style="justify-content:space-between; margin-bottom:12px">
        <h2 style="margin:0">Bias fundamental</h2>
        <button wire:click="refresh" wire:confirm="Jalankan ulang pipeline data + skor sekarang?">Perbarui data</button>
    </div>

    <table>
        <thead>
            <tr><th>Aset</th><th>Bias</th><th>Skor</th><th>Keyakinan*</th><th>Data</th><th>Risiko event</th><th></th></tr>
        </thead>
        <tbody>
        @forelse ($items as $row)
            @php
                $cls = $row['bias'] === 'bullish' ? 'up' : ($row['bias'] === 'bearish' ? 'down' : 'mut');
                $label = ['bullish' => 'NAIK', 'bearish' => 'TURUN', 'neutral' => 'NETRAL'][$row['bias']];
                $risk = $row['risk'] ?? [];
            @endphp
            <tr>
                <td><strong>{{ $row['asset_code'] }}</strong><br><small>{{ $row['name'] }}</small></td>
                <td class="{{ $cls }}">{{ $label }}</td>
                <td class="{{ $cls }}">{{ number_format($row['total'], 2) }}</td>
                <td>{{ round($row['confidence'] * 100) }}%</td>
                <td class="{{ $row['coverage'] < 0.7 ? 'warn' : 'mut' }}">{{ round($row['coverage'] * 100) }}%</td>
                <td>
                    @if (!empty($risk['blackout']))
                        <span class="down">JANGAN ENTRY</span><br>
                        <small>{{ collect($risk['blackout_events'])->pluck('title')->implode(', ') }}</small>
                    @elseif (!empty($risk['upcoming']))
                        <small>{{ $risk['upcoming'][0]['title'] }} ({{ substr($risk['upcoming'][0]['time'], 11, 5) }} UTC)</small>
                    @else
                        <small>—</small>
                    @endif
                </td>
                <td><button wire:click="toggle('{{ $row['asset_code'] }}')">{{ $open === $row['asset_code'] ? 'Tutup' : 'Faktor' }}</button></td>
            </tr>
            @if ($open === $row['asset_code'])
                <tr><td colspan="7">
                    <table>
                        <thead><tr><th>Faktor</th><th>Nilai</th><th>z</th><th>Skor</th><th>Bobot</th><th>Status</th></tr></thead>
                        <tbody>
                        @foreach ($details as $f)
                            <tr>
                                <td>{{ $f['factor'] }}</td>
                                <td>{{ isset($f['raw']) ? number_format($f['raw'], 4) : '—' }}</td>
                                <td>{{ isset($f['z']) ? number_format($f['z'], 2) : '—' }}</td>
                                <td class="{{ ($f['score'] ?? 0) > 0 ? 'up' : (($f['score'] ?? 0) < 0 ? 'down' : 'mut') }}">{{ $f['score'] ?? '—' }}</td>
                                <td>{{ $f['weight'] }}</td>
                                <td class="{{ $f['status'] === 'ok' ? 'mut' : 'warn' }}">{{ $f['status'] }}</td>
                            </tr>
                        @endforeach
                        </tbody>
                    </table>
                </td></tr>
            @endif
        @empty
            <tr><td colspan="7" class="mut">Belum ada skor. Jalankan <code>python -m app.cli backfill</code> di server engine.</td></tr>
        @endforelse
        </tbody>
    </table>
    <p><small>*Keyakinan adalah heuristik (besar skor × kesepakatan faktor × kelengkapan data), belum dikalibrasi lewat backtest.
        Bias adalah filter arah, bukan sinyal entry. "Data" di bawah 70% berarti banyak faktor tanpa data segar.</small></p>
</div>
