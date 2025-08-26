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
            signalOutput.innerHTML = `<h3 style="color: #ef5350;">❌ Помилка завантаження списків пар.</h3>`;
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
        .then(res => res.json())
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
            alert("Помилка мережі при оновленні списку обраного.");
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
        pairs.forEach(pair => sectionHtml += createPairButton(pair));
        sectionHtml += '</div></div>';
        return sectionHtml;
    }
    
    const allKnownPairs = [
        ...Object.values(staticData.forex || {}).flat(),
        ...(staticData.crypto || []),
        ...(staticData.stocks || []),
        ...(staticData.commodities || [])
    ];

    const watchlistDisplay = (staticData.watchlist || []).map(p_normalized => {
        return allKnownPairs.find(p_display => p_display.replace(/\//g, '') === p_normalized) || p_normalized;
    });

    html += createSection('⭐ Обране', watchlistDisplay);
    html += createSection('💎 Уся криптовалюта', staticData.crypto || []);
    
    if (staticData.forex && typeof staticData.forex === 'object') {
        Object.keys(staticData.forex).forEach(sessionName => {
            html += createSection(`💹 Усі валюти (${sessionName})`, staticData.forex[sessionName]);
        });
    }

    html += createSection('📈 Усі акції/індекси', staticData.stocks);
    html += createSection('🥇 Уся сировина', staticData.commodities);

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
    // ... (решта функції без змін)
}

function debounce(func, delay) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), delay);
    };
}

function showLoader(visible) {
    loader.className = visible ? '' : 'hidden';
}

// ... і решта функцій, які були раніше (drawChart, etc.)