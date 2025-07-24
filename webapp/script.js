// --- script.js ---

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
        ready: function () {},
        expand: function () {}
    };
} else {
    tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    console.log("Telegram WebApp object is ready.");
}

document.addEventListener('DOMContentLoaded', function () {
    showLoader(true);
    const initDataString = tg.initData ? `?initData=${encodeURIComponent(tg.initData)}` : '';

    const staticPairsUrl = `${API_BASE_URL}/api/get_pairs${initDataString}`;
    const activeMarketsUrl = `${API_BASE_URL}/api/get_active_markets`;

    Promise.all([
        fetch(staticPairsUrl).then(res => res.json()),
        fetch(activeMarketsUrl).then(res => res.json())
    ])
    .then(([staticData, activeData]) => {
        window.__WATCHLIST = staticData.watchlist || [];
        window.__INIT_DATA = tg.initData;
        populateLists(staticData, activeData);
        showLoader(false);
    })
    .catch(err => {
        console.error("Error fetching pair lists:", err);
        signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар. Перевірте консоль.";
        showLoader(false);
    });
});

function renderFavoriteButton(pair) {
    const isFav = window.__WATCHLIST.includes(pair);
    const label = isFav ? '✅' : '⭐';
    return `<button class="fav-btn" onclick="toggleFavorite(event, '${pair}')">${label}</button>`;
}

function toggleFavorite(e, pair) {
    e.stopPropagation();
    const isFav = window.__WATCHLIST.includes(pair);
    const url = `${API_BASE_URL}/api/toggle_fav?pair=${pair}&initData=${encodeURIComponent(window.__INIT_DATA)}`;
    fetch(url).then(res => res.json()).then(res => {
        if (res.success) {
            if (isFav) {
                window.__WATCHLIST = window.__WATCHLIST.filter(p => p !== pair);
            } else {
                window.__WATCHLIST.push(pair);
            }
            document.querySelectorAll(`[data-pair='${pair}'] .fav-btn`).forEach(btn => {
                btn.innerHTML = isFav ? '⭐' : '✅';
            });
        }
    });
}

function createPairButton(pair, assetType) {
    return `<div class="pair-item" data-pair="${pair}">
        <button class="pair-button" onclick="fetchSignal('${pair}', '${assetType}')">${pair}</button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(staticData, activeData) {
    let html = '';
    function section(title, items, assetType) {
        return `<div class="category">
            <div class="category-title">${title}</div>
            <div class="pair-list">
                ${items.map(p => createPairButton(p, assetType)).join('')}
            </div>
        </div>`;
    }
    if (activeData?.active_crypto?.length) html += section('⚡ Активна крипта', activeData.active_crypto, 'crypto');
    if (activeData?.active_stocks?.length) html += section('⚡ Активні акції', activeData.active_stocks, 'stocks');
    if (activeData?.active_forex?.length) html += section('⚡ Активні валюти', activeData.active_forex, 'forex');
    if (staticData.watchlist?.length) html += section('⭐ Обране', staticData.watchlist, getAssetType(staticData.watchlist[0]));
    if (staticData.crypto?.length) html += section('📈 Уся криптовалюта', staticData.crypto.slice(0, 12), 'crypto');
    if (staticData.stocks?.length) html += section('🏢 Усі акції', staticData.stocks, 'stocks');
    if (staticData.forex) {
        for (const session in staticData.forex) {
            html += section(`🌍 Усі валюти (${session})`, staticData.forex[session], 'forex');
        }
    }
    listsContainer.innerHTML = html;
}
