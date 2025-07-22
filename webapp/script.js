// script.js

const API_BASE_URL = "https://zigzag-bot-package.fly.dev";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");

// Змінено: Робимо код стійким до запуску поза Telegram
// Якщо об'єкт Telegram не існує, створюємо "заглушку" для тестування
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
    
    // Змінено: Коректно використовуємо initData
    const initDataString = tg.initData ? `?initData=${encodeURIComponent(tg.initData)}` : '';
    const apiUrl = `${API_BASE_URL}/api/get_pairs${initDataString}`;
    
    console.log("Requesting URL:", apiUrl);

    fetch(apiUrl)
        .then(res => {
            if (!res.ok) throw new Error(`Network response was not ok: ${res.statusText}`);
            return res.json();
        })
        .then(data => {
            console.log("Received data for pairs:", data);
            populateLists(data);
            showLoader(false);
        })
        .catch(err => {
            console.error("Error fetching pair lists:", err);
            signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар. Перевірте консоль.";
            showLoader(false);
        });
});

function populateLists(data) {
    console.log("Populating lists...");
    let html = '';

    if (Array.isArray(data.watchlist) && data.watchlist.length > 0) {
        html += '<div class="category"><div class="category-title">⭐ Обране</div><div class="pair-list">';
        data.watchlist.forEach(pair => {
            const assetType = getAssetType(pair);
            html += `<button class="pair-button" onclick="fetchSignal('${pair}', '${assetType}')">${pair}</button>`;
        });
        html += '</div></div>';
    }

    if (Array.isArray(data.crypto)) {
        html += '<div class="category"><div class="category-title">📈 Криптовалюти</div><div class="pair-list">';
        data.crypto.slice(0, 12).forEach(pair => {
            html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'crypto')">${pair}</button>`;
        });
        html += '</div></div>';
    }

    if (data.forex && typeof data.forex === 'object') {
        Object.keys(data.forex).forEach(sessionName => {
            // Виправлено: Прибрали зайву лапку в кінці рядка
            html += `<div class="category"><div class="category-title">🌍 Валюта (${sessionName})</div><div class="pair-list">`;
            data.forex[sessionName].forEach(pair => {
                html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'forex')">${pair}</button>`;
            });
            html += '</div></div>';
        });
    }

    if (Array.isArray(data.stocks)) {
        html += '<div class="category"><div class="category-title">🏢 Акції</div><div class="pair-list">';
        data.stocks.forEach(pair => {
            html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'stocks')">${pair}</button>`;
        });
        html += '</div></div>';
    }
    
    listsContainer.innerHTML = html;
    console.log("Lists populated.");
}

function fetchSignal(pair, assetType) {
    console.log(`fetchSignal called for pair: ${pair}`);
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую дані для ${pair}...`;
    Plotly.purge('chart');

    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}`;
    console.log("Requesting signal URL:", signalApiUrl);

    fetch(signalApiUrl)
        .then(res => {
            if (!res.ok) {
                return res.json().then(errData => {
                    throw new Error(errData.error || `Network response was not ok: ${res.statusText}`);
                }).catch(() => {
                    throw new Error(`Network response was not ok: ${res.statusText}`);
                });
            }
            return res.json();
        })
        .then(data => {
            if (data.error) {
                signalOutput.innerHTML = `❌ Помилка: ${data.error}`;
                showLoader(false);
                return;
            }
            signalOutput.innerHTML = `
                <strong>${data.pair}</strong>: ${data.signal}<br/>
                <strong>Ціна:</strong> ${data.price.toFixed(4)} | <strong>RSI:</strong> ${data.rsi.toFixed(2)}
            `;
            if (data.history && data.history.dates) {
                drawChart(pair, data.history);
            }
            showLoader(false);
        })
        .catch(err => {
            console.error(`Error fetching signal for ${pair}:`, err);
            signalOutput.innerHTML = `❌ Помилка: ${err.message}`;
            showLoader(false);
        });
}

function drawChart(pair, history) {
    const trace = {
        x: history.dates, close: history.close, high: history.high,
        low: history.low, open: history.open, type: 'candlestick',
        increasing: { line: { color: '#26a69a' } },
        decreasing: { line: { color: '#ef5350' } }
    };
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: tg.themeParams.text_color || '#fff' },
        xaxis: { rangeslider: { visible: false }, showgrid: false },
        yaxis: { showgrid: false },
        margin: { l: 35, r: 35, b: 35, t: 35 }
    };
    Plotly.newPlot('chart', [trace], layout);
}

function showLoader(visible) {
    loader.className = visible ? '' : 'hidden';
}

function getAssetType(pair) {
    if (pair.includes('/')) {
        return pair.includes('USDT') ? 'crypto' : 'forex';
    }
    return 'stocks';
}