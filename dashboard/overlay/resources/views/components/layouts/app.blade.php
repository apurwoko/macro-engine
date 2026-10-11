<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Macro Engine</title>
    <style>
        :root { --bg:#0f1115; --card:#181b22; --line:#2a2f3a; --txt:#e6e8ee; --mut:#8b93a5; --up:#2fbf71; --down:#ef5350; --warn:#f0b429; }
        * { box-sizing: border-box; }
        body { margin:0; background:var(--bg); color:var(--txt); font:14px/1.5 system-ui, sans-serif; }
        nav { display:flex; gap:16px; padding:12px 20px; border-bottom:1px solid var(--line); }
        nav a { color:var(--mut); text-decoration:none; } nav a:hover { color:var(--txt); }
        main { max-width:1100px; margin:0 auto; padding:20px; }
        table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; }
        th, td { padding:8px 12px; text-align:left; border-bottom:1px solid var(--line); }
        th { color:var(--mut); font-weight:500; font-size:12px; text-transform:uppercase; }
        .up { color:var(--up); } .down { color:var(--down); } .mut { color:var(--mut); } .warn { color:var(--warn); }
        .badge { padding:2px 8px; border-radius:10px; font-size:12px; border:1px solid var(--line); }
        .alert { padding:10px 14px; border-radius:8px; margin:0 0 14px; border:1px solid var(--warn); color:var(--warn); }
        .card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px; margin-bottom:16px; }
        input, select, button { background:#0f1115; color:var(--txt); border:1px solid var(--line); border-radius:6px; padding:6px 10px; }
        button { cursor:pointer; } button:hover { border-color:var(--mut); }
        .row { display:flex; gap:12px; flex-wrap:wrap; align-items:end; }
        label { display:flex; flex-direction:column; gap:4px; color:var(--mut); font-size:12px; }
        small { color:var(--mut); }
    </style>
    @livewireStyles
</head>
<body>
    <nav>
        <a href="{{ route('bias') }}" wire:navigate>Bias harian</a>
        <a href="{{ route('scenario') }}" wire:navigate>Skenario (repricing)</a>
    </nav>
    <main>{{ $slot }}</main>
    @livewireScripts
</body>
</html>
