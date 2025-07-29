// script.js

const API_BASE_URL = "https://zigzag-bot-package.fly.dev";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const historyContainer = document.getElementById("historyContainer");
const chartContainer = document.getElementById("chart");
const searchInput = document.getElementById('searchInput');
// --- ПОЧАТОК ЗМІН: Отримуємо контейнер для таймфреймів ---
const timeframeSelector = document.getElementById('timeframeSelector');
// --- КІНЕЦЬ ЗМІН ---

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
}

let currentWatchlist = [];
let initData = tg.initData || '';
// --- ПОЧАТОК ЗМІН: Зберігаємо поточний актив та таймфрейм ---
let currentPair = null;
let currentAssetType = null;
let currentTf = '1m';
// --- КІНЕЦЬ ЗМІН ---

document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    const initDataString = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    const rankedPairsUrl = `${API_BASE_URL}/api/get_ranked_pairs${initDataString}`;

    fetch(rankedPairsUrl)
        .then(res => res.json())
        .then(staticData => {
            if(staticData.error_message) console.warn(staticData.error_message);
            currentWatchlist = staticData.watchlist || [];
            // --- ПОЧАТОК ЗМІН: Додаємо сортування за активністю на фронтенді ---
            if (staticData.stocks) staticData.stocks = sortPairsByActivity(staticData.stocks, 'stocks');
            if (staticData.forex) {
                for (const session in staticData.forex) {
                    staticData.forex[session] = sortPairsByActivity(staticData.forex[session], 'forex');
                }
            }
            // --- КІНЕЦЬ ЗМІН ---
            populateLists(staticData);
            showLoader(false);
        })
        .catch(err => {
            console.error("Error fetching pair lists:", err);
            signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар.";
            showLoader(false);
        });

    searchInput.addEventListener('input', handleSearch);
});

// --- ПОЧАТОК ЗМІН: Функція сортування на фронтенді ---
function sortPairsByActivity(pairs, assetType) {
    // Проста імітація сортування на фронті, основна логіка на бекенді
    // Тут можна додати візуальне виділення активних пар
    return pairs; 
}
// --- КІНЕЦЬ ЗМІН ---

function handleSearch() {
    const searchTerm = searchInput.value.toUpperCase().trim();
    document.querySelectorAll('.pair-item').forEach(pair => {
        const ticker = pair.querySelector('.pair-button').textContent.toUpperCase();
        pair.style.display = ticker.includes(searchTerm) ? 'flex' : 'none';
    });
    document.querySelectorAll('.category').forEach(category => {
        const visiblePairs = category.querySelectorAll('.pair-item[style*="display: flex"]').length;
        category.style.display = visiblePairs > 0 ? 'block' : 'none';
    });
}

function renderFavoriteButton(pair) {
    const isFavorite = currentWatchlist.includes(pair);
    return `<button class="fav-btn" onclick="toggleFavorite(event, '${pair}')">${isFavorite ? '✅' : '⭐'}</button>`;
}

function toggleFavorite(event, pair) {
    event.stopPropagation();
    const button = event.currentTarget;
    const isCurrentlyFavorite = currentWatchlist.includes(pair);
    button.innerHTML = '⏳';
    fetch(`${API_BASE_URL}/api/toggle_watchlist?pair=${pair}&initData=${encodeURIComponent(initData)}`)
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                currentWatchlist = isCurrentlyFavorite ? currentWatchlist.filter(p => p !== pair) : [...currentWatchlist, pair];
                button.innerHTML = !isCurrentlyFavorite ? '✅' : '⭐';
            } else {
                button.innerHTML = isCurrentlyFavorite ? '✅' : '⭐';
            }
        }).catch(() => button.innerHTML = isCurrentlyFavorite ? '✅' : '⭐');
}

function createPairButton(pairData, assetType) {
    const pair = pairData.ticker;
    const isActive = pairData.active;
    const inactiveClass = isActive ? '' : 'inactive';
    return `<div class="pair-item ${inactiveClass}">
        <button class="pair-button" onclick="selectPair('${pair}', '${assetType}')">${pair}</button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(staticData) {
    let html = '';
    const createSection = (title, pairs, assetType) => {
        if (!pairs || !pairs.length) return '';
        return `<div class="category"><div class="category-title">${title}</div><div class="pair-list">` +
               pairs.map(p => createPairButton(typeof p === 'string' ? {ticker: p, active: true} : p, assetType)).join('') +
               `</div></div>`;
    };
    const watchlistData = staticData.watchlist.map(ticker => ({ ticker, active: true }));
    html += createSection('⭐ Обране', watchlistData, getAssetType);
    html += createSection('📈 Криптовалюта', staticData.crypto, 'crypto');
    if (staticData.forex) {
        Object.keys(staticData.forex).forEach(session => {
            html += createSection(`🌍 Forex (${session})`, staticData.forex[session], 'forex');
        });
    }
    html += createSection('🏢 Акції', staticData.stocks, 'stocks');
    listsContainer.innerHTML = html;
}

// --- ПОЧАТОК ЗМІН: Нові функції для вибору пари та таймфрейму ---
function selectPair(pair, assetType) {
    currentPair = pair;
    currentAssetType = assetType;
    timeframeSelector.innerHTML = ''; // Очищуємо селектор

    if (assetType === 'forex' || assetType === 'crypto') {
        const timeframes = ['1m', '5m', '15m'];
        let buttonsHtml = '<span>Таймфрейм:</span>';
        timeframes.forEach(tf => {
            buttonsHtml += `<button class="tf-button ${tf === currentTf ? 'active' : ''}" onclick="selectTimeframe('${tf}')">${tf}</button>`;
        });
        timeframeSelector.innerHTML = buttonsHtml;
    }
    
    fetchSignal();
}

function selectTimeframe(tf) {
    currentTf = tf;
    // Оновлюємо активну кнопку
    document.querySelectorAll('.tf-button').forEach(btn => {
        btn.classList.toggle('active', btn.textContent === tf);
    });
    fetchSignal(); // Перезапускаємо аналіз з новим таймфреймом
}

function fetchSignal() {
    if (!currentPair) return;

    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${currentPair} на ${currentTf}...`;
    signalOutput.style.textAlign = 'left';
    historyContainer.innerHTML = ''; 
    Plotly.purge('chart');

    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${currentPair}&tf=${currentTf}&initData=${encodeURIComponent(initData)}`;
    const mtaApiUrl = `${API_BASE_URL}/api/get_mta?pair=${currentPair}`;

    Promise.all([fetch(signalApiUrl).then(res => res.json()), fetch(mtaApiUrl).then(res => res.json())])
    .then(([signalData, mtaData]) => {
        if (signalData.error) {
            signalOutput.innerHTML = `❌ Помилка: ${signalData.error}`;
            timeframeSelector.innerHTML = ''; // Ховаємо кнопки, якщо помилка
            showLoader(false);
            return;
        }

        let html = `<div class="verdict-box ${signalData.verdict_level}">${signalData.verdict_text}</div>
                    <div class="pair-title">${signalData.pair} | ТФ: ${signalData.timeframe} | Ціна: ${signalData.price.toFixed(4)}</div>`;
        
        if (signalData.support || signalData.resistance) {
            const support = signalData.support ? `Підтримка: <strong>${signalData.support.toFixed(4)}</strong>` : '';
            const resistance = signalData.resistance ? `Опір: <strong>${signalData.resistance.toFixed(4)}</strong>` : '';
            html += `<div class="sr-levels">${support}${support && resistance ? ' | ' : ''}${resistance}</div>`;
        }

        if (signalData.reasons && signalData.reasons.length) {
            html += `<h4>Ключові фактори:</h4><ul class="reason-list">${signalData.reasons.map(r => `<li>${r}</li>`).join('')}</ul>`;
        }
        
        if (mtaData && mtaData.length) {
            html += '<h4>Мульти-таймфрейм аналіз (MTA):</h4><table class="mta-table"><tr>' +
                    mtaData.map(item => `<th>${item.tf}</th>`).join('') + '</tr><tr>' +
                    mtaData.map(item => `<td class="${item.signal.toLowerCase()}">${item.signal}</td>`).join('') + '</tr></table>';
        }

        signalOutput.innerHTML = html;
        if (signalData.history && signalData.history.dates.length > 0) drawChart(signalData.history);
        else chartContainer.innerHTML = `<div class="no-chart">Графік недоступний</div>`;
        
        if (initData) fetchHistory(currentPair);
        showLoader(false);
    })
    .catch(err => {
        console.error(`Error fetching signal for ${currentPair}:`, err);
        signalOutput.innerHTML = `❌ Помилка отримання сигналу.`;
        showLoader(false);
    });
}
// --- КІНЕЦЬ ЗМІН ---

function fetchHistory(pair) {
    fetch(`${API_BASE_URL}/api/signal_history?pair=${pair}&initData=${encodeURIComponent(initData)}`)
        .then(res => res.json())
        .then(historyData => {
            if (historyData && historyData.length > 0) displaySignalHistory(historyData);
        });
}

function displaySignalHistory(history) {
    let html = '<h4>Історія сигналів</h4><table class="history-table"><thead><tr><th>Час</th><th>Ціна</th><th>Сигнал</th><th>Сила</th></tr></thead><tbody>';
    history.forEach(item => {
        const date = new Date(item.timestamp.replace(' ', 'T') + 'Z');
        const formattedDate = `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')} ${date.getDate().toString().padStart(2, '0')}.${(date.getMonth() + 1).toString().padStart(2, '0')}`;
        html += `<tr><td>${formattedDate}</td><td>${item.price ? item.price.toFixed(4) : 'N/A'}</td><td class="signal-${item.signal_type.toLowerCase()}">${item.signal_type}</td><td>${item.bull_percentage}%</td></tr>`;
    });
    historyContainer.innerHTML = html + '</tbody></table>';
}

function drawChart(history) {
    const trace = { x: history.dates, close: history.close, high: history.high, low: history.low, open: history.open, type: 'candlestick', increasing: { line: { color: '#26a69a' } }, decreasing: { line: { color: '#ef5350' } } };
    const layout = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: tg.themeParams.text_color || '#fff' }, xaxis: { rangeslider: { visible: false }, showgrid: false }, yaxis: { showgrid: false }, margin: { l: 35, r: 10, b: 35, t: 10 } };
    Plotly.newPlot('chart', [trace], layout, {responsive: true});
}

function showLoader(visible) {
    loader.className = visible ? '' : 'hidden';
}

function getAssetType(pair) {
    if (pair.includes('/')) return pair.includes('USDT') ? 'crypto' : 'forex';
    return 'stocks';
}