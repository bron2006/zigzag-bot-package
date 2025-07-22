// script.js

const API_BASE_URL = "https://zigzag-bot-package.fly.dev";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");

let tg;
if (!window.Telegram || !window.Telegram.WebApp) {
    console.warn("Telegram WebApp object not found. Running in browser mode with mock data.");
    tg = { 
        themeParams: { bg_color: '#1a1a1a', text_color: '#ffffff' }, 
        initData: '',
        ready: function() {},
        expand: function() {}
    };
} else {
    tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    console.log("Telegram WebApp object is ready.");
}

document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    const initDataString = tg.initData ? `?initData=${encodeURIComponent(tg.initData)}` : '';
    
    // --- ПОЧАТОК ЗМІН: Завантажуємо одразу два типи даних ---
    const staticPairsUrl = `${API_BASE_URL}/api/get_pairs${initDataString}`;
    const activeMarketsUrl = `${API_BASE_URL}/api/get_active_markets`;

    // Виконуємо два запити одночасно
    Promise.all([
        fetch(staticPairsUrl).then(res => res.json()),
        fetch(activeMarketsUrl).then(res => res.json())
    ])
    .then(([staticData, activeData]) => {
        console.log("Received static pairs:", staticData);
        console.log("Received active markets:", activeData);
        
        // Передаємо обидва набори даних у функцію populateLists
        populateLists(staticData, activeData);
        showLoader(false);
    })
    .catch(err => {
        console.error("Error fetching pair lists:", err);
        signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар. Перевірте консоль.";
        showLoader(false);
    });
    // --- КІНЕЦЬ ЗМІН ---
});

// --- ПОЧАТОК ЗМІН: Функція тепер приймає дані про активні ринки ---
function populateLists(staticData, activeData) {
    console.log("Populating lists...");
    let html = '';

    // Додаємо нові розділи для активних пар, якщо вони є
    if (activeData) {
        if (Array.isArray(activeData.active_crypto) && activeData.active_crypto.length > 0) {
            html += '<div class="category"><div class="category-title">⚡ Активна крипта</div><div class="pair-list">';
            activeData.active_crypto.forEach(pair => {
                html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'crypto')">${pair}</button>`;
            });
            html += '</div></div>';
        }
        if (Array.isArray(activeData.active_stocks) && activeData.active_stocks.length > 0) {
            html += '<div class="category"><div class="category-title">⚡ Активні акції</div><div class="pair-list">';
            activeData.active_stocks.forEach(pair => {
                html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'stocks')">${pair}</button>`;
            });
            html += '</div></div>';
        }
        if (Array.isArray(activeData.active_forex) && activeData.active_forex.length > 0) {
            html += '<div class="category"><div class="category-title">⚡ Активні валюти</div><div class="pair-list">';
            activeData.active_forex.forEach(pair => {
                html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'forex')">${pair}</button>`;
            });
            html += '</div></div>';
        }
    }

    // Рендеримо звичайні списки
    if (Array.isArray(staticData.watchlist) && staticData.watchlist.length > 0) {
        html += '<div class="category"><div class="category-title">⭐ Обране</div><div class="pair-list">';
        staticData.watchlist.forEach(pair => {
            const assetType = getAssetType(pair);
            html += `<button class="pair-button" onclick="fetchSignal('${pair}', '${assetType}')">${pair}</button>`;
        });
        html += '</div></div>';
    }

    if (Array.isArray(staticData.crypto)) {
        html += '<div class="category"><div class="category-title">📈 Уся криптовалюта</div><div class="pair-list">';
        staticData.crypto.slice(0, 12).forEach(pair => {
            html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'crypto')">${pair}</button>`;
        });
        html += '</div></div>';
    }

    if (staticData.forex && typeof staticData.forex === 'object') {
        Object.keys(staticData.forex).forEach(sessionName => {
            html += `<div class="category"><div class="category-title">🌍 Усі валюти (${sessionName})</div><div class="pair-list">`;
            staticData.forex[sessionName].forEach(pair => {
                html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'forex')">${pair}</button>`;
            });
            html += '</div></div>';
        });
    }

    if (Array.isArray(staticData.stocks)) {
        html += '<div class="category"><div class="category-title">🏢 Усі акції</div><div class="pair-list">';
        staticData.stocks.forEach(pair => {
            html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'stocks')">${pair}</button>`;
        });
        html += '</div></div>';
    }
    
    listsContainer.innerHTML = html;
    console.log("Lists populated.");
}
// --- КІНЕЦЬ ЗМІН ---

function fetchSignal(pair, assetType) {
    // ... (код залишається без змін)
    console.log(`fetchSignal called for pair: ${pair}`);
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую детальний аналіз для ${pair}...`;
    signalOutput.style.textAlign = 'left';
    Plotly.purge('chart');
    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}`;
    fetch(signalApiUrl)
        .then(res => {
            if (!res.ok) {
                return res.json().then(errData => { throw new Error(errData.error || `Network response was not ok: ${res.statusText}`); });
            }
            return res.json();
        })
        .then(data => {
            if (data.error) {
                signalOutput.innerHTML = `❌ Помилка: ${data.error}`;
                signalOutput.style.textAlign = 'center';
                showLoader(false);
                return;
            }
            const supportText = data.support ? data.support.toFixed(4) : 'N/A';
            const resistanceText = data.resistance ? data.resistance.toFixed(4) : 'N/A';
            const reasonsList = data.reasons.map(reason => `<li>${reason}</li>`).join('');
            let candleHtml = '';
            if (data.candle_pattern && data.candle_pattern.text) {
                candleHtml = `<div style="margin-bottom: 10px;"><strong>Свічковий патерн:</strong><br>${data.candle_pattern.text}</div>`;
            }
            let volumeHtml = '';
            if (data.volume_analysis) {
                volumeHtml = `<div style="margin-bottom: 10px;"><strong>Аналіз об'єму:</strong><br>${data.volume_analysis}</div>`;
            }
            signalOutput.innerHTML = `<div style="margin-bottom: 10px;"><strong>${data.pair}</strong> | Ціна: ${data.price.toFixed(4)}</div><div style="margin-bottom: 10px;"><strong>Баланс сил:</strong><br>🐂 Бики: ${data.bull_percentage}% ⬆️ | 🐃 Ведмеді: ${data.bear_percentage}% ⬇️</div>${candleHtml}<div style="margin-bottom: 10px;"><strong>Рівні S/R:</strong><br>Підтримка: ${supportText} | Опір: ${resistanceText}</div>${volumeHtml}<div><strong>Ключові фактори:</strong><ul style="margin: 5px 0 0 20px; padding: 0;">${reasonsList}</ul></div>`;
            if (data.history && data.history.dates) {
                drawChart(pair, data.history);
            }
            showLoader(false);
        })
        .catch(err => {
            console.error(`Error fetching signal for ${pair}:`, err);
            signalOutput.innerHTML = `❌ Помилка: ${err.message}`;
            signalOutput.style.textAlign = 'center';
            showLoader(false);
        });
}

function drawChart(pair, history) {
    // ... (код залишається без змін)
    const trace = { x: history.dates, close: history.close, high: history.high, low: history.low, open: history.open, type: 'candlestick', increasing: { line: { color: '#26a69a' } }, decreasing: { line: { color: '#ef5350' } } };
    const layout = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: tg.themeParams.text_color || '#fff' }, xaxis: { rangeslider: { visible: false }, showgrid: false }, yaxis: { showgrid: false }, margin: { l: 35, r: 35, b: 35, t: 35 } };
    Plotly.newPlot('chart', [trace], layout);
}

function showLoader(visible) {
    // ... (код залишається без змін)
    loader.className = visible ? '' : 'hidden';
}

function getAssetType(pair) {
    // ... (код залишається без змін)
    if (pair.includes('/')) { return pair.includes('USDT') ? 'crypto' : 'forex'; }
    return 'stocks';
}