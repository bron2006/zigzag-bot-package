// script.js

const API_BASE_URL = "https://zigzag-bot-package.fly.dev";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const historyContainer = document.getElementById("historyContainer");
const chartContainer = document.getElementById("chart");
const searchInput = document.getElementById('searchInput');
const timeframeSelector = document.getElementById('timeframeSelector');

let tg;
if (!window.Telegram || !window.Telegram.WebApp) {
    console.warn("Telegram WebApp object not found. Running in browser mode.");
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
let currentPair = null;
let currentAssetType = null;
let currentTf = '1m';

document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    const initDataString = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    const rankedPairsUrl = `${API_BASE_URL}/api/get_ranked_pairs${initDataString}`;

    fetch(rankedPairsUrl)
        .then(res => res.json())
        .then(staticData => {
            if(staticData.error_message) console.warn(staticData.error_message);
            currentWatchlist = staticData.watchlist || [];
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

function handleSearch() {
    const searchTerm = searchInput.value.toUpperCase().trim();
    document.querySelectorAll('.category').forEach(category => {
        let hasVisiblePairs = false;
        category.querySelectorAll('.pair-item').forEach(pairItem => {
            const ticker = pairItem.querySelector('.pair-button').textContent.toUpperCase();
            if (ticker.includes(searchTerm)) {
                pairItem.style.display = 'flex';
                hasVisiblePairs = true;
            } else {
                pairItem.style.display = 'none';
            }
        });
        category.style.display = hasVisiblePairs ? 'block' : 'none';
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
                if (isCurrentlyFavorite) {
                    currentWatchlist = currentWatchlist.filter(p => p !== pair);
                } else {
                    currentWatchlist.push(pair);
                }
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
    
    // --- ПОЧАТОК ВИПРАВЛЕННЯ: Правильна логіка для assetTypeResolver ---
    const createSection = (title, pairs, assetTypeResolver) => {
        if (!pairs || !pairs.length) return '';
        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        
        pairs.forEach(pairData => {
            const data = typeof pairData === 'string' ? { ticker: pairData, active: true } : pairData;
            // Визначаємо тип активу для кожної пари. Якщо assetTypeResolver - це функція, викликаємо її.
            const assetType = typeof assetTypeResolver === 'function' ? assetTypeResolver(data.ticker) : assetTypeResolver;
            sectionHtml += createPairButton(data, assetType);
        });
        
        sectionHtml += '</div></div>';
        return sectionHtml;
    };
    // --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    const watchlistData = staticData.watchlist.map(ticker => ({ ticker, active: true }));
    html += createSection('⭐ Обране', watchlistData, getAssetType); // Передаємо функцію getAssetType
    html += createSection('📈 Криптовалюта', staticData.crypto, 'crypto');
    if (staticData.forex) {
        Object.keys(staticData.forex).forEach(session => {
            html += createSection(`🌍 Forex (${session})`, staticData.forex[session], 'forex');
        });
    }
    html += createSection('🏢 Акції', staticData.stocks, 'stocks');
    listsContainer.innerHTML = html;
}

function selectPair(pair, assetType) {
    currentPair = pair;
    currentAssetType = assetType;
    currentTf = '1m'; // Скидаємо таймфрейм до стандартного при виборі нової пари
    timeframeSelector.innerHTML = ''; 

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
    document.querySelectorAll('.tf-button').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
    fetchSignal();
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
        showLoader(false);
        if (signalData.error) {
            signalOutput.innerHTML = `<div class="verdict-box neutral">❌ Помилка: ${signalData.error}</div>`;
            timeframeSelector.innerHTML = '';
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
    })
    .catch(err => {
        showLoader(false);
        console.error(`Error fetching signal for ${currentPair}:`, err);
        signalOutput.innerHTML = `❌ Помилка отримання сигналу.`;
    });
}

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