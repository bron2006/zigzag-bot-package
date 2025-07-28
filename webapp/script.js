// script.js

const API_BASE_URL = "https://zigzag-bot-package.fly.dev";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const historyContainer = document.getElementById("historyContainer");
const chartContainer = document.getElementById("chart");

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
    const rankedPairsUrl = `${API_BASE_URL}/api/get_ranked_pairs${initDataString}`;

    fetch(rankedPairsUrl)
        .then(res => res.json())
        .then(staticData => {
            console.log("Received static pairs:", staticData);
            if(staticData.error_message) {
                console.warn(staticData.error_message);
            }
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

function createPairButton(pairData, assetType) {
    const pair = pairData.ticker;
    const isActive = pairData.active;
    const inactiveClass = isActive ? '' : 'inactive';
    
    return `<div class="pair-item ${inactiveClass}">
        <button class="pair-button" onclick="fetchSignal('${pair}', '${assetType}')">${pair}</button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(staticData) {
    let html = '';
    function createSection(title, pairs, assetTypeResolver) {
        if (!pairs || pairs.length === 0) return '';
        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        
        const pairList = Array.isArray(pairs) ? pairs : (staticData.watchlist.includes(pairs.ticker) ? [pairs] : []);

        pairList.forEach(pairData => {
            const data = typeof pairData === 'string' ? { ticker: pairData, active: true } : pairData;
            const assetType = typeof assetTypeResolver === 'function' ? assetTypeResolver(data.ticker) : assetTypeResolver;
            sectionHtml += createPairButton(data, assetType);
        });
        sectionHtml += '</div></div>';
        return sectionHtml;
    }

    const watchlistData = staticData.watchlist.map(ticker => ({ ticker, active: true }));
    html += createSection('⭐ Обране', watchlistData, getAssetType);

    html += createSection('📈 Уся криптовалюта', staticData.crypto || [], 'crypto');

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
    historyContainer.innerHTML = ''; 
    Plotly.purge('chart');

    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}&initData=${encodeURIComponent(initData)}`;
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

        let html = `
            <div class="verdict-box ${signalData.verdict_level}">
                ${signalData.verdict_text}
            </div>
            <div class="pair-title">${signalData.pair} | Ціна: ${signalData.price.toFixed(4)}</div>
        `;
        
        if (signalData.support || signalData.resistance) {
            const supportText = signalData.support ? `Підтримка: <strong>${signalData.support.toFixed(4)}</strong>` : '';
            const resistanceText = signalData.resistance ? `Опір: <strong>${signalData.resistance.toFixed(4)}</strong>` : '';
            const separator = signalData.support && signalData.resistance ? ' | ' : '';
            
            html += `<div class="sr-levels">${supportText}${separator}${resistanceText}</div>`;
        }

        if (signalData.reasons && signalData.reasons.length) {
            html += `<h4>Ключові фактори:</h4><ul class="reason-list">${signalData.reasons.map(r => `<li>${r}</li>`).join('')}</ul>`;
        }
        
        if (Array.isArray(mtaData) && mtaData.length > 0) {
            html += '<h4>Мульти-таймфрейм аналіз (MTA):</h4><table class="mta-table"><tr>';
            mtaData.forEach(item => { html += `<th>${item.tf}</th>`; });
            html += '</tr><tr>';
            mtaData.forEach(item => {
                const signalClass = item.signal.toLowerCase();
                html += `<td class="${signalClass}">${item.signal}</td>`;
            });
            html += '</tr></table>';
        }

        signalOutput.innerHTML = html;

        if (signalData.history && signalData.history.dates && signalData.history.dates.length > 0) {
            drawChart(pair, signalData.history);
        } else {
            chartContainer.innerHTML = `<div class="no-chart">Графік недоступний</div>`;
        }
        
        if (initData) {
            fetchHistory(pair);
        }

        showLoader(false);
    })
    .catch(err => {
        console.error(`Error fetching signal for ${pair}:`, err);
        signalOutput.innerHTML = `❌ Помилка отримання сигналу. Перевірте з'єднання.`;
        signalOutput.style.textAlign = 'center';
        showLoader(false);
    });
}

function fetchHistory(pair) {
    const historyApiUrl = `${API_BASE_URL}/api/signal_history?pair=${pair}&initData=${encodeURIComponent(initData)}`;
    fetch(historyApiUrl)
        .then(res => res.json())
        .then(historyData => {
            if (historyData && historyData.length > 0) {
                displaySignalHistory(historyData);
            }
        })
        .catch(err => console.error("Error fetching signal history:", err));
}

function displaySignalHistory(history) {
    let html = '<h4>Історія сигналів</h4>';
    html += '<table class="history-table"><thead><tr><th>Час</th><th>Ціна</th><th>Сигнал</th><th>Сила</th></tr></thead><tbody>';

    history.forEach(item => {
        const date = new Date(item.timestamp.replace(' ', 'T') + 'Z');
        const formattedDate = `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')} ${date.getDate().toString().padStart(2, '0')}.${(date.getMonth() + 1).toString().padStart(2, '0')}`;
        const signalClass = `signal-${item.signal_type.toLowerCase()}`;
        const price = item.price ? item.price.toFixed(4) : 'N/A';

        html += `
            <tr>
                <td>${formattedDate}</td>
                <td>${price}</td>
                <td class="${signalClass}">${item.signal_type}</td>
                <td>${item.bull_percentage}%</td>
            </tr>
        `;
    });

    html += '</tbody></table>';
    historyContainer.innerHTML = html;
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
        margin: { l: 35, r: 10, b: 35, t: 10 }
    };
    Plotly.newPlot('chart', [trace], layout, {responsive: true});
}

function showLoader(visible) {
    loader.className = visible ? '' : 'hidden';
}

function getAssetType(pair) {
    if (pair.includes('/')) return pair.includes('USDT') ? 'crypto' : 'forex';
    return 'stocks';
}