<?php

// Tambahkan entri ini ke array yang di-return oleh config/services.php

return [
    // ...

    'macro_engine' => [
        'url' => env('MACRO_ENGINE_URL', 'http://127.0.0.1:8000'),
        'key' => env('MACRO_ENGINE_KEY'),
    ],
];
