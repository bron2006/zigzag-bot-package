// webapp/script.js

const API_BASE_URL = "."; // Use relative path for production
// const API_BASE_URL = "https://zigzag-bot-package.fly.dev"; // Use for local testing

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const historyContainer = document.getElementById("historyContainer");
const chartContainer = document.getElementById("chart");

let tg;
// Mock Telegram WebApp object for browser-based testing
if (!window.Telegram || !window.Telegram.WebApp || !window.Telegram.WebApp.initData) {
    console.warn("Telegram WebApp object not found. Running in browser mode with mock data.");
    tg = { 
        themeParams: { bg_color: '#1a1a1a', text_color: '#ffffff' }, 
        initData: '', // Mock initData can be placed here for testing
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

function fetchInitialData() {
    showLoader(true);
    const cacheBuster = `&_=${new Date().getTime()}`;
    const initDataString = initData ? `?initData=${encodeURIComponent(initData)}` : '?';
    const rankedPairsUrl = `${API_BASE_URL}/api/get_ranked_pairs${initDataString}${cacheBuster}`;

    fetch(rankedPairsUrl)
        .then(res => res.json())
        .then(response => {
            if (response.status === "initializing") {
                console.log("Backend is initializing, retrying in 2 seconds...");
                signalOutput.innerHTML = "⏳ Ініціалізація з'єднання з торговим сервером...";
                signalOutput.style.textAlign = 'center';
                setTimeout(fetchInitialData, 2000); // Poll again
            } else if (response.status === "ready") {
                console.log("Received static pairs:", response.data);
                signalOutput.innerHTML = ""; // Clear initializing message
                currentWatchlist = response.data.watchlist || [];
                populateLists(response.data);
                showLoader(false);
            } else {
                throw new Error(response.error || "Невідома помилка формату відповіді.");
            }
        })
        .catch(err => {
            console.error("Error fetching pair lists:", err);
            signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар. Спробуйте оновити сторінку.";
            signalOutput.style.textAlign = 'center';
            showLoader(false);
        });
}

document.addEventListener('DOMContentLoaded', fetchInitialData);

function renderFavoriteButton(pair) {
    const isFavorite = currentWatchlist.includes(pair);
    const icon = isFavorite ? '✅' : '⭐';
    return `<button class="fav-btn" onclick="toggleFavorite(event, '${pair}')">${icon}</button>`;
}

function toggleFavorite(event, pair) {
    event.stopPropagation();
    const button = event.currentTarget;
    const isCurrentlyFavorite = currentWatchlist.includes(pair);
    button.disabled = true;

    const url = `${API_BASE_URL}/api/toggle_watchlist?pair=${pair}&initData=${encodeURIComponent(initData)}`;
    fetch(url)
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                if (isCurrentlyFavorite) {
                    currentWatchlist = currentWatchlist.filter(p => p !== pair);
                    button.innerHTML = '⭐';
                } else {
                    currentWatchlist.push(pair);
                    button.innerHTML = '✅';
                }
            }
        })
        .catch(err => console.error(err))
        .finally(() => button.disabled = false);
}

function createPairButton(pairData) {
    const pair = pairData.ticker;
    const isActive = pairData.active;
    const inactiveClass = isActive ? '' : 'inactive';
    
    return `<div class="pair-item ${inactiveClass}">
        <button class="pair-button" onclick="fetchSignal('${pair}')" ${!isActive ? 'disabled' : ''}>${pair}</button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(staticData) {
    let html = '';
    const createSection = (title, pairs) => {
        if (!pairs || pairs.length === 0) return '';
        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        pairs.forEach(pairData => {
            sectionHtml += createPairButton(pairData);
        });
        sectionHtml += '</div></div>';
        return sectionHtml;
    };

    const allPairs = [
        ...(staticData.forex ? Object.values(staticData.forex).flat() : []),
        ...(staticData.crypto || []),
        ...(staticData.stocks || [])
    ];
    
    const watchlistData = staticData.watchlist
        .map(ticker => allPairs.find(p => p.ticker === ticker))
        .filter(Boolean); // Filter out any tickers not found in allPairs

    html += createSection('⭐ Обране', watchlistData);

    if (staticData.forex) {
        Object.keys(staticData.forex).forEach(sessionName => {
            html += createSection(`🌍 Валюти (${sessionName})`, staticData.forex[sessionName]);
        });
    }
    html += createSection('📈 Криптовалюта', staticData.crypto || []);
    html += createSection('🏢 Акції', staticData.stocks || []);

    listsContainer.innerHTML = html;
}

function fetchSignal(pair) {
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую аналіз для ${pair}...`;
    signalOutput.style.textAlign = 'center';
    historyContainer.innerHTML = ''; 
    Plotly.purge('chart');

    const cacheBuster = `&_=${new Date().getTime()}`;
    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}&initData=${encodeURIComponent(initData)}${cacheBuster}`;
    const mtaApiUrl = `${API_BASE_URL}/api/get_mta?pair=${pair}${cacheBuster}`;

    Promise.all([
        fetch(signalApiUrl).then(res => res.json()),
        fetch(mtaApiUrl).then(res => res.json())
    ])
    .then(([signalData, mtaData]) => {
        signalOutput.style.textAlign = 'left';
        if (signalData.error) {
            throw new Error(signalData.error);
        }
        
        const priceStr = (signalData.price || 0).toFixed(5);
        const supportStr = signalData.support ? signalData.support.toFixed(5) : null;
        const resistanceStr = signalData.resistance ? signalData.resistance.toFixed(5) : null;

        let html = `
            <div class="verdict-box ${signalData.verdict_level || 'neutral'}">
                ${signalData.verdict_text || 'Н/Д'}
            </div>
            <div class="pair-title">${signalData.pair} | Ціна: ${priceStr}</div>
        `;
        
        if (supportStr || resistanceStr) {
            html += `<div class="sr-levels">`;
            if (supportStr) html += `Підтримка: <strong>${supportStr}</strong>`;
            if (supportStr && resistanceStr) html += ` | `;
            if (resistanceStr) html += `Опір: <strong>${resistanceStr}</strong>`;
            html += `</div>`;
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
    })
    .catch(err => {
        console.error(`Error fetching signal for ${pair}:`, err);
        signalOutput.innerHTML = `❌ Помилка: ${err.message || "Перевірте з'єднання."}`;
        signalOutput.style.textAlign = 'center';
    })
    .finally(() => {
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
        const price = item.price ? item.price.toFixed(5) : 'N/A';
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
        margin: { l: 40, r: 10, b: 35, t: 10 }
    };
    Plotly.newPlot('chart', [trace], layout, {responsive: true});
}

function showLoader(visible) {
    loader.className = visible ? '' : 'hidden';
}