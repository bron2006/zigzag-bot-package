const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");

// Завантажуємо списки пар при відкритті
document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    // Передаємо ініціалізаційні дані для отримання watchlist
    fetch(`/api/get_pairs?initData=${tg.initDataUnsafe ? encodeURIComponent(tg.initData) : ''}`)
        .then(res => res.json())
        .then(data => {
            populateLists(data);
            showLoader(false);
        })
        .catch(err => {
            signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар.";
            showLoader(false);
        });
});

function populateLists(data) {
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
    data.crypto.slice(0, 12).forEach(pair => { // Показуємо перші 12
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
}

function fetchSignal(pair, assetType) {
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую дані для ${pair}...`;
    Plotly.purge('chart');

    fetch(`/api/signal?pair=${pair}`)
        .then(res => res.json())
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
            signalOutput.innerHTML = `❌ Не вдалося отримати сигнал.`;
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