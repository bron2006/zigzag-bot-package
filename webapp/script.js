const API_BASE_URL = window.API_BASE_URL || "https://fallback.example.com";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalContainer = document.getElementById("signalContainer"); // <-- Додано для скролу
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
let allData = {}; // Зберігаємо всі дані для фільтрації

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
        });
    });

    fetch(staticPairsUrl)
        .then(res => {
            if (res.status === 401) { throw new Error("⛔ Немає доступу. Будь ласка, перезапустіть Web App через Telegram."); }
            if (!res.ok) { throw new Error(`HTTP status ${res.status}: ${res.statusText}`); }
            return res.json();
        })
        .then(staticData => {
            allData = staticData; // Зберігаємо повний набір даних
            currentWatchlist = staticData.watchlist || [];
            populateLists(allData); // Перше відображення
            showLoader(false);
        })
        .catch(err => {
            console.error("Error fetching pair lists:", err);
            signalOutput.innerHTML = `...`; // Повідомлення про помилку
            showLoader(false);
        });
    
    // --- ПОЧАТОК ЗМІН: Логіка пошуку ---
    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', debounce((event) => {
        const query = event.target.value.toLowerCase();
        if (!query) {
            populateLists(allData); // Якщо поле порожнє, показуємо все
            return;
        }
        
        // Фільтруємо дані
        const filteredData = {
            forex: (allData.forex || []).map(session => ({
                ...session,
                pairs: session.pairs.filter(p => p.toLowerCase().includes(query))
            })).filter(session => session.pairs.length > 0),
            crypto: (allData.crypto || []).filter(p => p.toLowerCase().includes(query)),
            stocks: (allData.stocks || []).filter(p => p.toLowerCase().includes(query)),
            commodities: (allData.commodities || []).filter(p => p.toLowerCase().includes(query)),
            watchlist: (allData.watchlist || []).filter(p => p.toLowerCase().includes(query))
        };
        
        populateLists(filteredData);
    }, 300));
    // --- КІНЕЦЬ ЗМІН ---
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

function populateLists(data) {
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
    
    const allPairs = [
        ...Object.values(data.forex || []).map(session => session.pairs).flat(),
        ...(data.crypto || []),
        ...(data.stocks || []),
        ...(data.commodities || [])
    ];
    const watchlistDisplay = (currentWatchlist || []).map(p_normalized => {
        return allPairs.find(p_display => p_display.replace(/\//g, '') === p_normalized) || p_normalized;
    });

    html += createSection('⭐ Обране', watchlistDisplay);
    html += createSection('💎 Уся криптовалюта', data.crypto || []);
    
    if (Array.isArray(data.forex)) {
        data.forex.forEach(session => {
            html += createSection(session.title, session.pairs);
        });
    }

    html += createSection('📈 Усі акції/індекси', data.stocks);
    html += createSection('🥇 Уся сировина', data.commodities);

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
                // ... (код обробки помилок) ...
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
            
            html += `...`; // HTML для звіту
            signalOutput.innerHTML = html;

            if (signalData.history && signalData.history.dates) {
                drawChart(pair, signalData.history);
            }
            
            showLoader(false);

            // --- ПОЧАТОК ЗМІН: Автоматичний скрол ---
            signalContainer.scrollIntoView({ behavior: 'smooth' });
            // --- КІНЕЦЬ ЗМІН ---
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
        Plotly.newPlot('chart', [{...}], {...});
    } catch(e) { console.error("Error drawing chart:", e); }
}

function showLoader(visible) {
    loader.className = visible ? '' : 'hidden';
}

function debounce(func, delay) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), delay);
    };
}