// script.js

const API_BASE_URL = "https://zigzag-bot-package.fly.dev";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const historyContainer = document.getElementById("historyContainer");
const chartContainer = document.getElementById("chart");
const searchInput = document.getElementById("searchInput"); // Пошук

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
let currentlyDisplayedPair = null; // Для логіки оновлення

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

// --- ПОЧАТОК ЗМІН: Логіка для пошуку ---
searchInput.addEventListener('input', function() {
    const query = searchInput.value.toLowerCase();
    const allPairItems = document.querySelectorAll('.pair-item');
    allPairItems.forEach(item => {
        const pairName = item.querySelector('.pair-button').textContent.toLowerCase();
        if (pairName.includes(query)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
});
// --- КІНЕЦЬ ЗМІН ---

function createPairButton(pairData, assetType) {
    // ... (код без змін) ...
}

function populateLists(staticData) {
    // ... (код без змін) ...
}


// --- ПОЧАТОК ЗМІН: Логіка для оновлення по другому кліку ---
function fetchSignal(pair, assetType) {
    let forceRefresh = false;
    if (currentlyDisplayedPair === pair) {
        forceRefresh = true;
    }
    currentlyDisplayedPair = pair;

    console.log(`fetchSignal called for pair: ${pair}, refresh: ${forceRefresh}`);
    showLoader(true);
    signalOutput.innerHTML = `⏳ ${forceRefresh ? 'Примусово оновлюю' : 'Отримую'} аналіз для ${pair}...`;
    signalOutput.style.textAlign = 'left';
    historyContainer.innerHTML = ''; 
    Plotly.purge('chart');

    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}&initData=${encodeURIComponent(initData)}${forceRefresh ? '&refresh=true' : ''}`;
    const mtaApiUrl = `${API_BASE_URL}/api/get_mta?pair=${pair}`;
// --- КІНЕЦЬ ЗМІН ---

    Promise.all([
        fetch(signalApiUrl).then(res => res.json()),
        fetch(mtaApiUrl).then(res => res.json())
    ])
    .then(([signalData, mtaData]) => {
        if (signalData.error) {
            signalOutput.innerHTML = `❌ Помилка: ${signalData.error}`;
            signalOutput.style.textAlign = 'center';
            currentlyDisplayedPair = null; // Скидаємо, якщо помилка
            showLoader(false);
            return;
        }
        // ... (решта коду функції без змін)
    })
    .catch(err => {
        // ...
        currentlyDisplayedPair = null; // Скидаємо, якщо помилка
        // ...
    });
}
// ... (решта файлу без змін)