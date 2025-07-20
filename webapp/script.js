// Повідомляємо Telegram, що Web App готовий до роботи
Telegram.WebApp.ready();
Telegram.WebApp.expand();

console.log("WebApp script started.");

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");

// Завантажуємо списки пар при відкритті
document.addEventListener('DOMContentLoaded', function() {
    console.log("DOM content loaded. Fetching pairs...");
    showLoader(true);
    
    const apiUrl = `/api/get_pairs?initData=${tg.initDataUnsafe ? encodeURIComponent(tg.initData) : ''}`;
    console.log("Requesting URL:", apiUrl);

    fetch(apiUrl)
        .then(res => {
            console.log("Received response for /api/get_pairs. Status:", res.status);
            if (!res.ok) {
                throw new Error(`Network response was not ok: ${res.statusText}`);
            }
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
    console.log("Populating lists with data...");
    let html = '';

    // Список обраного
    if (data.watchlist && data.watchlist.length > 0) {
        html += '<div class="category"><div class="category-title">⭐ Обране</div><div class="pair-list">';
        data.watchlist.forEach(pair => {
            const assetType = getAssetType(pair);
            html += `<button class="pair-button" onclick="fetchSignal('${pair}', '${assetType}')">${pair}</button>`;
        });
        html += '</div></div>';
    }

    // Криптовалюти
    html += '<div class="category"><div class="category-title">📈 Криптовалюти</div><div class="pair-list">';
    data.crypto.slice(0, 12).forEach(pair => {
        html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'crypto')">${pair}</button>`;
    });
    html += '</div></div>';

    // Акції
    html += '<div class="category"><div class="category-title">🏢 Акції</div><div class="pair-list">';
    data.stocks.forEach(pair => {
        html += `<button class="pair-button" onclick="fetchSignal('${pair}', 'stocks')">${pair}</button>`;
    });
    html += '</div></div>';
    
    listsContainer.innerHTML = html;
    console.log("Lists populated.");
}

function fetchSignal(pair, assetType) {
    console.log(`fetchSignal called for pair: ${pair}, asset: ${assetType}`);
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую дані для ${pair}...`;
    Plotly.purge('chart');

    const signalApiUrl = `/api/signal?pair=${pair}`;
    console.log("Requesting signal URL:", signalApiUrl);

    fetch(signalApiUrl)
        .then(res => {
            console.log(`Received response for /api/signal for ${pair}. Status:`, res.status);
            if (!res.ok) {
                throw new Error(`Network response was not ok: ${res.statusText}`);
            }
            return res.json();
        })
        .then(data => {
            console.log(`Received signal data for ${pair}:`, data);
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
            signalOutput.innerHTML = `❌ Не вдалося отримати сигнал. Перевірте консоль. Помилка: ${err.message}`;
            showLoader(false);
        });
}

function drawChart(pair, history) {
    // ... (код цієї функції не змінюється)
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