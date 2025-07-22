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
        ready: function () {},
        expand: function () {}
    };
} else {
    tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    console.log("Telegram WebApp object is ready.");
}

document.body.style.backgroundColor = tg.themeParams.bg_color || '#1a1a1a';
document.body.style.color = tg.themeParams.text_color || '#ffffff';

document.addEventListener('DOMContentLoaded', function () {
    showLoader(true);
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
    let html = '<button onclick="location.reload()" class="refresh-button">🔄 Оновити список</button>';

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
    signalOutput.innerHTML = `⏳ Отримую детальний аналіз для ${pair}...`;
    signalOutput.style.textAlign = 'left';
    signalOutput.style.border = 'none';
    Plotly.purge('chart');

    document.querySelectorAll('.pair-button').forEach(btn => btn.classList.remove('active'));
    const clickedButton = Array.from(document.querySelectorAll('.pair-button')).find(btn => btn.textContent === pair);
    if (clickedButton) clickedButton.classList.add('active');

    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}`;
    console.log("Requesting signal URL:", signalApiUrl);

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
                candleHtml = `<div><strong>Свічковий патерн:</strong><br>${data.candle_pattern.text}</div>`;
            }

            let volumeHtml = '';
            if (data.volume_analysis) {
                volumeHtml = `<div><strong>Аналіз об'єму:</strong><br>${data.volume_analysis}</div>`;
            }

            let color = '#ccc';
            if (data.bull_percentage >= 70) color = '#00e676';
            else if (data.bear_percentage >= 70) color = '#ff1744';
            signalOutput.style.border = `2px solid ${color}`;

            const now = new Date();
            const timeString = now.toLocaleTimeString();

            signalOutput.innerHTML = `
                <div><strong>${data.pair}</strong> | Ціна: ${data.price.toFixed(4)}</div>
                <div><strong>Баланс сил:</strong> 🐂 ${data.bull_percentage}% ⬆️ | 🐃 ${data.bear_percentage}% ⬇️</div>
                ${candleHtml}
                <div><strong>Рівні S/R:</strong> Підтримка: ${supportText} | Опір: ${resistanceText}</div>
                ${volumeHtml}
                <div><strong>Ключові фактори:</strong><ul>${reasonsList}</ul></div>
                <div style="font-size: 12px; margin-top: 10px; color: var(--hint-color)">🕒 Оновлено: ${timeString}</div>
            `;

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
    const chartDiv = document.getElementById('chart');
    chartDiv.style.opacity = '0';
    setTimeout(() => { chartDiv.style.opacity = '1'; }, 50);

    const trace = {
        x: history.dates,
        close: history.close,
        high: history.high,
        low: history.low,
        open: history.open,
        type: 'candlestick',
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
