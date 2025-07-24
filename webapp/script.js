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

let currentWatchlist = [];
let initData = tg.initData || '';

document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    const initDataString = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    const staticPairsUrl = `${API_BASE_URL}/api/get_pairs${initDataString}`;

    // ТИМЧАСОВО: прибираємо get_active_markets (викликає OOM)
    fetch(staticPairsUrl)
        .then(res => res.json())
        .then(staticData => {
            console.log("Received static pairs:", staticData);
            currentWatchlist = staticData.watchlist || [];
            populateLists(staticData);
            showLoader(false);
        })
        .catch(err => {
            console.error("Error fetching pair lists:", err);
            signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар.";
            showLoader(false);
        });
});

function renderFavoriteButton(pair) {
    const isFavorite = currentWatchlist.includes(pair);
    const icon = isFavorite ? '✅' : '⭐';
    return `<button class="fav-btn" onclick="toggleFavorite(event, '${pair}')">${icon}</button>`;
}

function toggleFavorite(event, pair) {
    event.stopPropagation();
    const button = event.currentTarget;
    const isCurrentlyFavorite = currentWatchlist.includes(pair);
    button.innerHTML = isCurrentlyFavorite ? '⭐' : '✅';
    const url = `${API_BASE_URL}/api/toggle_watchlist?pair=${pair}&initData=${encodeURIComponent(initData)}`;
    fetch(url)
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                if (isCurrentlyFavorite) {
                    currentWatchlist = currentWatchlist.filter(p => p !== pair);
                } else {
                    currentWatchlist.push(pair);
                }
            } else {
                button.innerHTML = isCurrentlyFavorite ? '✅' : '⭐';
                alert("Не вдалося оновити список обраного.");
            }
        })
        .catch(err => {
            button.innerHTML = isCurrentlyFavorite ? '✅' : '⭐';
            alert("Помилка мережі при оновленні списку обраного.");
            console.error(err);
        });
}

function createPairButton(pair, assetType) {
    return `<div class="pair-item">
        <button class="pair-button" onclick="fetchSignal('${pair}', '${assetType}')">${pair}</button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(staticData) {
    let html = '';
    function createSection(title, pairs, assetTypeResolver) {
        if (!Array.isArray(pairs) || pairs.length === 0) return '';
        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        pairs.forEach(pair => {
            const assetType = typeof assetTypeResolver === 'function' ? assetTypeResolver(pair) : assetTypeResolver;
            sectionHtml += createPairButton(pair, assetType);
        });
        sectionHtml += '</div></div>';
        return sectionHtml;
    }

    html += createSection('⭐ Обране', staticData.watchlist, getAssetType);
    html += createSection('📈 Уся криптовалюта', staticData.crypto ? staticData.crypto.slice(0, 12) : [], 'crypto');

    if (staticData.forex && typeof staticData.forex === 'object') {
        Object.keys(staticData.forex).forEach(sessionName => {
            html += createSection(`🌍 Усі валюти (${sessionName})`, staticData.forex[sessionName], 'forex');
        });
    }

    html += createSection('🏢 Усі акції', staticData.stocks, 'stocks');

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

        let mtaHtml = '';
        if (Array.isArray(mtaData) && mtaData.length > 0) {
            mtaHtml += '<div class="mta-container"><strong>Мульти-таймфрейм аналіз (MTA):</strong><table class="mta-table"><tr>';
            mtaData.forEach(item => { mtaHtml += `<th>${item.tf}</th>`; });
            mtaHtml += '</tr><tr>';
            mtaData.forEach(item => {
                const signalClass = item.signal.toLowerCase();
                mtaHtml += `<td class="${signalClass}">${item.signal}</td>`;
            });
            mtaHtml += '</tr></table></div>';
        }

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

        if (signalData.history && signalData.history.dates) {
            drawChart(pair, signalData.history);
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
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
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
    if (pair.includes('/')) return pair.includes('USDT') ? 'crypto' : 'forex';
    return 'stocks';
}
