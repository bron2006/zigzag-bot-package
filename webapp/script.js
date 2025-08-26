const API_BASE_URL = window.API_BASE_URL || "https://fallback.example.com";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalContainer = document.getElementById("signalContainer");
const signalOutput = document.getElementById("signalOutput");
const historyContainer = document.getElementById("historyContainer");

let tg;
if (!window.Telegram || !window.Telegram.WebApp) {
    tg = { themeParams: { bg_color: '#1a1a1a', text_color: '#ffffff' }, initData: '' };
} else {
    tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
}

let currentWatchlist = [];
let initData = tg.initData || '';
let currentTimeframe = '1m';
let allData = {};
let lastSelectedPair = null; // <-- Зберігаємо останню обрану пару

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
            
            // --- ПОЧАТОК ЗМІН: Оновлюємо сигнал, якщо пара вже обрана ---
            if (lastSelectedPair) {
                fetchSignal(lastSelectedPair);
            }
            // --- КІНЕЦЬ ЗМІН ---
        });
    });

    fetch(staticPairsUrl)
        .then(res => {
            if (res.status === 401) { throw new Error("⛔ Немає доступу. Будь ласка, перезапустіть Web App через Telegram."); }
            if (!res.ok) { throw new Error(`HTTP status ${res.status}: ${res.statusText}`); }
            return res.json();
        })
        .then(staticData => {
            allData = staticData;
            currentWatchlist = staticData.watchlist || [];
            populateLists(allData);
            showLoader(false);
        })
        .catch(err => {
            console.error("Error fetching pair lists:", err);
            signalOutput.innerHTML = `<h3 style="color: #ef5350;">❌ Помилка завантаження списків пар.</h3><p>${err.message}</p>`;
            showLoader(false);
        });
    
    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', debounce((event) => {
        const query = event.target.value.toLowerCase();
        populateLists(allData, query);
    }, 300));
});

function renderFavoriteButton(pair) {
    const pairNormalized = pair.replace(/\//g, '');
    const isFavorite = currentWatchlist.includes(pairNormalized);
    const icon = isFavorite ? '✅' : '⭐';
    return `<button class="fav-btn" onclick="toggleFavorite(event, this, '${pair}')">${icon}</button>`;
}

function toggleFavorite(event, button, pair) {
    event.stopPropagation();
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

function populateLists(data, query = '') {
    // ... (код populateLists без змін) ...
}

function fetchSignal(pair) {
    lastSelectedPair = pair; // <-- Зберігаємо останню обрану пару
    showLoader(true);
    // ... (решта функції без змін) ...
}

// Повні версії функцій, які були скорочені раніше
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
// ... і так далі для всіх функцій