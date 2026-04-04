const API_BASE_URL = window.API_BASE_URL || "https://fallback.example.com";
const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const scannerControls = document.getElementById('scannerControls');
const liveSignalsContainer = document.getElementById('liveSignalsContainer');
const signalContainer = document.getElementById('signalContainer');

let tg = window.Telegram.WebApp;
tg.ready(); tg.expand();

let currentWatchlist = [];
let initData = tg.initData || '';
let currentExpiration = '1m';
let allData = {};
let lastSelectedPair = null;

const debouncedFetchSignal = debounce(fetchSignal, 300);

document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    const initDataQuery = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    const staticPairsUrl = `${API_BASE_URL}/api/get_pairs${initDataQuery}`;
    fetch(staticPairsUrl).then(res => res.json()).then(staticData => {
        allData = staticData;
        currentWatchlist = (staticData.watchlist || []).map(p => p.replace(/\//g, ''));
        populateLists(allData);
        showLoader(false);
    }).catch(err => {
        signalOutput.innerHTML = `<h3 style="color: #ef5350;">❌ Помилка завантаження списків пар.</h3>`;
        showLoader(false);
    });

    fetch(`${API_BASE_URL}/api/scanner/status${initDataQuery}`).then(res => res.json()).then(data => updateScannerButtons(data));

    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    eventSource.onmessage = function(event) {
        const signalData = JSON.parse(event.data);
        if (signalData._ping) return;
        displayLiveSignal(signalData);
    };

    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', debounce((event) => { populateLists(allData, event.target.value); }, 300));
});

function populateLists(data, query = '') {
    let html = '';
    const queryLower = query.toLowerCase();
    function createPairButton(pair) {
        return `<div class="pair-item"><button class="pair-button" data-pair="${pair}">${pair}</button>${renderFavoriteButton(pair)}</div>`;
    }
    function createSection(title, pairs) {
        if (!Array.isArray(pairs) || pairs.length === 0) return '';
        const filteredPairs = pairs.filter(p => p.toLowerCase().includes(queryLower));
        if (filteredPairs.length === 0) return '';
        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        filteredPairs.forEach(pair => sectionHtml += createPairButton(pair));
        return sectionHtml + '</div></div>';
    }
    if (data.forex) data.forex.forEach(session => html += createSection(session.title, session.pairs));
    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);
    listsContainer.innerHTML = html;
    listsContainer.querySelectorAll('.pair-button').forEach(button => {
        button.addEventListener('click', (event) => debouncedFetchSignal(event.target.dataset.pair));
    });
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую дані для ${pair}...`;
    const initDataQuery = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${initDataQuery.replace('?', '&')}`)
        .then(res => res.json()).then(signalData => {
            signalOutput.innerHTML = formatSignalAsHtml(signalData, currentExpiration);
        }).finally(() => {
            signalContainer.scrollIntoView({ behavior: 'smooth' });
            showLoader(false);
        });
}

function formatSignalAsHtml(signalData, expiration) {
    if (signalData.error) return `❌ Помилка: ${signalData.error}`;
    const { pair, price, verdict_text, score } = signalData;
    return `
        <div class="signal-header"><strong>${pair} (${expiration})</strong></div>
        <div class="price-display-manual"><div class="price-label">Ціна входу</div><div class="signal-price">${price ? price.toFixed(5) : "N/A"}</div></div>
        <div class="verdict">${verdict_text}</div>
        <div class="power-balance"><span>🐂 Бики: ${score}%</span><span>🐃 Ведмеді: ${100 - score}%</span></div>
    `;
}

function renderFavoriteButton(pair) { return `<button class="fav-btn">⭐</button>`; }
function updateScannerButtons(s) {}
function displayLiveSignal(s) {}
function showLoader(visible) { loader.className = visible ? '' : 'hidden'; }
function debounce(func, delay) { let timeout; return function(...args) { clearTimeout(timeout); timeout = setTimeout(() => func.apply(this, args), delay); }; }