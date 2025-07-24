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
    
    const staticPairsUrl = `${API_BASE_URL}/api/get_pairs${initDataString}`;
    const activeMarketsUrl = `${API_BASE_URL}/api/get_active_markets`;

    Promise.all([
        fetch(staticPairsUrl).then(res => res.json()),
        fetch(activeMarketsUrl).then(res => res.json())
    ])
    .then(([staticData, activeData]) => {
        console.log("Received static pairs:", staticData);
        console.log("Received active markets:", activeData);
        populateLists(staticData, activeData);
        showLoader(false);
    })
    .catch(err => {
        console.error("Error fetching pair lists:", err);
        signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар. Перевірте консоль.";
        showLoader(false);
    });
});

function populateLists(staticData, activeData) {
    let html = '';
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
}

function fetchSignal(pair, assetType) {
    console.log(`fetchSignal called for pair: ${pair}`);
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую детальний аналіз для ${pair}...`;
    signalOutput.style.textAlign = 'left';
    Plotly.purge('chart');

    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}`;
    const mtaApiUrl = `${API_BASE_URL}/api/get_mta?pair=${pair}`;

    Promise.all([
        fetch(signalApiUrl).then(res => res.json()),
        fetch(mtaApiUrl).then(res => res.json())
    ])
    .then(([signalData, mtaData]) => {
        if (signalData.error) {
            signalOutput.innerHTML = `❌ Помилка: ${signalData.error}`;
            signalOutput.style.textAlign = 'center';
            showLoader(false);
            return;
        }

        const arrow = signalData.bull_percentage >= 50 ? '⬆️' : '⬇️';
        const supportText = signalData.support ? signalData.support.toFixed(4) : 'N/A';
        const resistanceText = signalData.resistance ? signalData.resistance.toFixed(4) : 'N/A';
        const reasonsList = signalData.reasons.map(r => `<li>${r}</li>`).join('');
        let candleHtml = signalData.candle_pattern?.text ? `<div style="margin-bottom:10px"><strong>Свічковий патерн:</strong><br>${signalData.candle_pattern.text}</div>` : '';
        let volumeHtml = signalData.volume_analysis ? `<div style="margin-bottom:10px"><strong>Аналіз об'єму:</strong><br>${signalData.volume_analysis}</div>` : '';

        // --- ПОЧАТОК НОВОГО КОДУ: Генеруємо таблицю МТА ---
        let mtaHtml = '';
        if (Array.isArray(mtaData) && mtaData.length > 0) {
            mtaHtml += '<div class="mta-container">';
            mtaHtml += '<strong>Мульти-таймфрейм аналіз (MTA):</strong>';
            mtaHtml += '<table class="mta-table"><tr>';
            mtaData.forEach(item => { mtaHtml += `<th>${item.tf}</th>`; });
            mtaHtml += '</tr><tr>';
            mtaData.forEach(item => {
                const signalClass = item.signal.toLowerCase();
                mtaHtml += `<td class="${signalClass}">${item.signal}</td>`;
            });
            mtaHtml += '</tr></table></div>';
        }
        // --- КІНЕЦЬ НОВОГО КОДУ ---

        signalOutput.innerHTML = `
            <div style="font-size: 32px; text-align: center; margin-bottom: 15px;">${arrow}</div>
            <div style="margin-bottom: 10px;"><strong>${signalData.pair}</strong> | Ціна: ${signalData.price.toFixed(4)}</div>
            <div style="margin-bottom: 10px;"><strong>Баланс сил:</strong><br>🐂 Бики: ${signalData.bull_percentage}% ⬆️ | 🐃 Ведмеді: ${signalData.bear_percentage}% ⬇️</div>
            ${candleHtml}
            <div style="margin-bottom: 10px;"><strong>Рівні S/R:</strong><br>Підтримка: ${supportText} | Опір: ${resistanceText}</div>
            ${volumeHtml}
            <div><strong>Ключові фактори:</strong><ul style="margin: 5px 0 0 20px; padding: 0;">${reasonsList}</ul></div>
            ${mtaHtml}
        `;
        
        if (signalData.history && signalData.history.dates) drawChart(pair, signalData.history);
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
    const trace = { x: history.dates, close: history.close, high: history.high, low: history.low, open: history.open, type: 'candlestick', increasing: { line: { color: '#26a69a' } }, decreasing: { line: { color: '#ef5350' } } };
    const layout = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: tg.themeParams.text_color || '#fff' }, xaxis: { rangeslider: { visible: false }, showgrid: false }, yaxis: { showgrid: false }, margin: { l: 35, r: 35, b: 35, t: 35 } };
    Plotly.newPlot('chart', [trace], layout);
}

function showLoader(visible) {
    loader.className = visible ? '' : 'hidden';
}

function getAssetType(pair) {
    if (pair.includes('/')) return pair.includes('USDT') ? 'crypto' : 'forex';
    return 'stocks';
}