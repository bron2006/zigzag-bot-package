const API_BASE_URL = window.API_BASE_URL || "https://fallback.example.com";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const historyContainer = document.getElementById("historyContainer");

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
let currentTimeframe = '1m';

document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    const initDataString = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    const staticPairsUrl = `${API_BASE_URL}/api/get_pairs?v=1${initDataString}`;

    const timeframeButtons = document.querySelectorAll('.tf-button');
    timeframeButtons.forEach(button => {
        button.addEventListener('click', () => {
            timeframeButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            currentTimeframe = button.dataset.tf;
            console.log(`Timeframe changed to: ${currentTimeframe}`);
        });
    });

    fetch(staticPairsUrl)
        .then(res => {
            if (res.status === 401) { throw new Error("⛔ Немає доступу. Будь ласка, перезапустіть Web App через Telegram."); }
            if (!res.ok) { throw new Error(`HTTP status ${res.status}: ${res.statusText}`); }
            return res.json();
        })
        .then(staticData => {
            console.log("Received static pairs:", staticData);
            currentWatchlist = staticData.watchlist || [];
            populateLists(staticData);
            showLoader(false);
        })
        .catch(err => {
            console.error("Error fetching pair lists:", err);
            signalOutput.innerHTML = `
                <div style="text-align: left; font-family: monospace; word-wrap: break-word;">
                    <h3 style="color: #ef5350;">❌ Помилка завантаження списків пар.</h3>
                    <p><strong>URL:</strong><br>${staticPairsUrl}</p>
                    <p><strong>Помилка:</strong><br>${err.name}: ${err.message}</p>
                </div>
            `;
            showLoader(false);
        });
});

function renderFavoriteButton(pair) {
    const pairNormalized = pair.replace(/\//g, '');
    const isFavorite = currentWatchlist.includes(pairNormalized);
    const icon = isFavorite ? '✅' : '⭐';
    return `<button class="fav-btn" onclick="toggleFavorite(event, '${pair}')">${icon}</button>`;
}

function toggleFavorite(event, pair) {
    event.stopPropagation();
    const button = event.currentTarget;
    const isCurrentlyFavorite = button.innerHTML.includes('✅');

    const url = `${API_BASE_URL}/api/toggle_watchlist?pair=${pair}&initData=${encodeURIComponent(initData)}`;
    
    button.innerHTML = isCurrentlyFavorite ? '⭐' : '✅';

    fetch(url)
        .then(res => {
            if (res.status === 401) { throw new Error("Unauthorized"); }
            return res.json();
        })
        .then(data => {
            if (!data.success) {
                button.innerHTML = isCurrentlyFavorite ? '✅' : '⭐';
                alert("Не вдалося оновити список обраного.");
            } else {
                const pairNormalized = pair.replace(/\//g, '');
                if (isCurrentlyFavorite) {
                    currentWatchlist = currentWatchlist.filter(p => p !== pairNormalized);
                } else {
                    currentWatchlist.push(pairNormalized);
                }
            }
        })
        .catch(err => {
            button.innerHTML = isCurrentlyFavorite ? '✅' : '⭐';
            alert(`Помилка мережі при оновленні списку обраного: ${err.message}`);
            console.error(err);
        });
}

function createPairButton(pair) {
    return `<div class="pair-item">
        <button class="pair-button" data-pair="${pair}">${pair}</button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(staticData) {
    let html = '';
    function createSection(title, pairs) {
        if (!Array.isArray(pairs) || pairs.length === 0) return '';
        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        pairs.forEach(pair => {
            sectionHtml += createPairButton(pair);
        });
        sectionHtml += '</div></div>';
        return sectionHtml;
    }
    
    // --- ПОЧАТОК ЗМІН: Адаптуємо під нову структуру даних ---
    const allPairs = [
        ...Object.values(staticData.forex || []).map(session => session.pairs).flat(),
        ...(staticData.crypto || []),
        ...(staticData.stocks || []),
        ...(staticData.commodities || [])
    ];

    const watchlistDisplay = (staticData.watchlist || []).map(p_normalized => {
        return allPairs.find(p_display => p_display.replace(/\//g, '') === p_normalized) || p_normalized;
    });

    html += createSection('⭐ Обране', watchlistDisplay);
    html += createSection('💎 Уся криптовалюта', staticData.crypto || []);
    
    if (Array.isArray(staticData.forex)) {
        staticData.forex.forEach(session => {
            html += createSection(session.title, session.pairs);
        });
    }

    html += createSection('📈 Усі акції/індекси', staticData.stocks);
    html += createSection('🥇 Уся сировина', staticData.commodities);
    // --- КІНЕЦЬ ЗМІН ---

    listsContainer.innerHTML = html;

    const debouncedFetch = debounce(fetchSignal, 300);
    listsContainer.querySelectorAll('.pair-button').forEach(button => {
        button.addEventListener('click', (event) => {
            const pair = event.target.dataset.pair;
            debouncedFetch(pair);
        });
    });
}

function fetchSignal(pair) {
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую аналіз для ${pair} (${currentTimeframe})...`;
    signalOutput.style.textAlign = 'left';
    historyContainer.innerHTML = ''; 
    Plotly.purge('chart');

    const initDataString = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentTimeframe}${initDataString}`;
    
    fetch(signalApiUrl)
        .then(res => {
            if (res.status === 401) { throw new Error("⛔ Немає доступу. Будь ласка, перезапустіть Web App через Telegram."); }
            return res.json();
        })
        .then(signalData => {
            if (signalData.error) {
                let errorText = `❌ Помилка: ${signalData.error}`;
                if (signalData.details) {
                    errorText += `<br><br><strong>Деталі:</strong><pre>${signalData.details}</pre>`;
                }
                signalOutput.innerHTML = errorText;
                signalOutput.style.textAlign = 'left';
                showLoader(false);
                return;
            }

            let html = '';
            if (signalData.special_warning) {
                html += `<div class="special-warning">${signalData.special_warning}</div>`;
            }

            let arrow = '🟡';
            if (signalData.bull_percentage > 55) {
                arrow = '⬆️';
            } else if (signalData.bull_percentage < 45) {
                arrow = '⬇️';
            }

            const supportText = signalData.support ? signalData.support.toFixed(5) : 'N/A';
            const resistanceText = signalData.resistance ? signalData.resistance.toFixed(5) : 'N/A';
            const reasons = Array.isArray(signalData.reasons) ? signalData.reasons : [];
            const reasonsList = reasons.map(r => `<li>${r}</li>`).join('');
            let candleHtml = signalData.candle_pattern?.text ? `<div style="margin-bottom:10px"><strong>Свічковий патерн:</strong><br>${signalData.candle_pattern.text}</div>` : '';
            let volumeHtml = signalData.volume_analysis ? `<div style="margin-bottom:10px"><strong>Аналіз об'єму:</strong><br>${signalData.volume_analysis}</div>` : '';
            
            html += `
                <div style="font-size: 32px; text-align: center; margin-bottom: 15px;">${arrow}</div>
                <div style="margin-bottom: 10px;"><strong>${signalData.pair} (${currentTimeframe})</strong> | Ціна: ${signalData.price.toFixed(5)}</div>
                <div style="margin-bottom: 10px;"><strong>Баланс сил:</strong><br>🐂 Бики: ${signalData.bull_percentage}% ⬆️ | 🐃 Ведмеді: ${signalData.bear_percentage}% ⬇️</div>
                ${candleHtml}
                <div style="margin-bottom: 10px;"><strong>Рівні S/R:</strong><br>Підтримка: ${supportText} | Опір: ${resistanceText}</div>
                ${volumeHtml}
                <div><strong>Ключові фактори:</strong><ul style="margin: 5px 0 0 20px; padding: 0;">${reasonsList}</ul></div>
            `;
            signalOutput.innerHTML = html;

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
    if (!window.Plotly) return;
    try {
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
    } catch(e) {
        console.error("Error drawing chart:", e);
    }
}

function showLoader(visible) {
    loader.className = visible ? '' : 'hidden';
}

function getAssetType(pair) {
    if (pair.includes('XAU')) return 'commodities';
    if (pair.includes('/')) return pair.includes('USD') ? 'crypto' : 'forex';
    return 'stocks';
}

function debounce(func, delay) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), delay);
    };
}