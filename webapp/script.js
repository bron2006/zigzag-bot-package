// script.js

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
    if (!initData) {
        const warning = document.createElement('div');
        warning.textContent = "⚠️ Ви в демо-режимі. Функція 'Обране' недоступна. Для повного доступу відкрийте додаток у Telegram.";
        warning.className = "demo-warning";
        document.body.prepend(warning);
        document.querySelector('.container').classList.add('in-demo');
    }

    showLoader(true);
    const initDataString = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    const staticPairsUrl = `${API_BASE_URL}/api/get_pairs${initDataString}`;

    fetch(staticPairsUrl)
        .then(res => res.json())
        .then(staticData => {
            console.log("Received static pairs:", staticData);
            currentWatchlist = staticData.watchlist || [];
            populateLists(staticData);
            showLoader(false);
        })
        .catch(err => {
            console.error("Error fetching pair lists:", err);
            signalOutput.innerHTML = "❌ Не вдалося завантажити списки пар.";
            showLoader(false);
        });

    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.trim().toLowerCase();
        
        document.querySelectorAll('.pair-item').forEach(item => {
            const buttonText = item.querySelector('.pair-button').textContent.trim().toLowerCase();
            item.style.display = buttonText.includes(query) ? 'flex' : 'none';
        });

        document.querySelectorAll('.category').forEach(category => {
            const visibleItems = category.querySelectorAll('.pair-item[style*="display: flex"]');
            category.style.display = visibleItems.length > 0 ? 'block' : 'none';
        });
    });
});

function renderFavoriteButton(pair) {
    if (!initData) {
        return `<button class="fav-btn" disabled style="cursor: not-allowed;">⭐</button>`;
    }
    const isFavorite = currentWatchlist.includes(pair);
    const icon = isFavorite ? '✅' : '⭐';
    return `<button class="fav-btn" onclick="toggleFavorite(event, '${pair}')">${icon}</button>`;
}

function toggleFavorite(event, pair) {
    event.stopPropagation();
    if (!initData) {
        alert("Ця функція доступна лише в Telegram.");
        return;
    }
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

function createPairButton(pair, assetType) {
    return `<div class="pair-item">
        <button class="pair-button" onclick="fetchSignal('${pair}', '${assetType}')">${pair}</button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(staticData) {
    let html = '';
    function createSection(title, pairs, assetTypeResolver) {
        if (!Array.isArray(pairs) || pairs.length === 0) return '';
        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        pairs.forEach(pair => {
            const assetType = typeof assetTypeResolver === 'function' ? assetTypeResolver(pair) : assetTypeResolver;
            sectionHtml += createPairButton(pair, assetType);
        });
        sectionHtml += '</div></div>';
        return sectionHtml;
    }

    if (staticData.watchlist && staticData.watchlist.length > 0) {
        html += createSection('⭐ Обране', staticData.watchlist, getAssetType);
    }
    html += createSection('📈 Криптовалюта', staticData.crypto || [], 'crypto');
    if (staticData.forex && typeof staticData.forex === 'object') {
        Object.keys(staticData.forex).forEach(sessionName => {
            html += createSection(`🌍 Валюти (${sessionName})`, staticData.forex[sessionName], 'forex');
        });
    }
    html += createSection('🏢 Акції', staticData.stocks || [], 'stocks');
    listsContainer.innerHTML = html;
}

function fetchSignal(pair, assetType) {
    console.log(`fetchSignal called for pair: ${pair}`);
    showLoader(true);
    signalOutput.innerHTML = `⏳ О