const API_BASE_URL = window.API_BASE_URL || "https://fallback.example.com";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const scannerToggleButton = document.getElementById('scannerToggleButton');
const liveSignalsContainer = document.getElementById('liveSignalsContainer');

let tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

let currentWatchlist = [];
let initData = tg.initData || '';
let currentTimeframe = '1m';
let allData = {};
let lastSelectedPair = null;

const debouncedFetchSignal = debounce(fetchSignal, 300);

document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    const initDataQuery = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    const staticPairsUrl = `${API_BASE_URL}/api/get_pairs${initDataQuery}`;

    fetch(staticPairsUrl)
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            return res.json();
        })
        .then(staticData => {
            allData = staticData;
            currentWatchlist = staticData.watchlist || [];
            populateLists(allData);
            showLoader(false);
        })
        .catch(err => {
            signalOutput.innerHTML = `<h3 style="color: #ef5350;">❌ Помилка завантаження списків пар.</h3><p>${err.message}</p>`;
            showLoader(false);
        });
    
    fetch(`${API_BASE_URL}/api/scanner/status${initDataQuery}`)
        .then(res => res.json())
        .then(data => updateScannerButton(data.enabled));

    scannerToggleButton.addEventListener('click', () => {
        fetch(`${API_BASE_URL}/api/scanner/toggle${initDataQuery}`)
            .then(res => res.json())
            .then(data => updateScannerButton(data.enabled));
    });

    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    
    eventSource.onmessage = function(event) {
        const signalData = JSON.parse(event.data);
        displayLiveSignal(signalData);
    };
    
    eventSource.onerror = function(err) {
        console.error("EventSource failed:", err);
    };
    
    const timeframeButtons = document.querySelectorAll('.tf-button');
    timeframeButtons.forEach(button => {
        button.addEventListener('click', () => {
            timeframeButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            currentTimeframe = button.dataset.tf;
            if (lastSelectedPair) {
                debouncedFetchSignal(lastSelectedPair);
            }
        });
    });
    
    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', debounce((event) => {
        populateLists(allData, event.target.value);
    }, 300));
});

function updateScannerButton(isEnabled) {
    if (isEnabled) {
        scannerToggleButton.textContent = '✅ Сканер УВІМКНЕНО';
        scannerToggleButton.classList.add('enabled');
    } else {
        scannerToggleButton.textContent = '❌ Сканер ВИМКНЕНО';
        scannerToggleButton.classList.remove('enabled');
    }
}

function displayLiveSignal(signalData) {
    const signalDiv = document.createElement('div');
    signalDiv.className = 'live-signal';
    
    const verdict = signalData.verdict_text || '...';
    const pair = signalData.pair || 'N/A';
    const score = signalData.bull_percentage || 50;
    
    let signalClass = 'neutral';
    if (score >= 65) signalClass = 'buy';
    if (score <= 35) signalClass = 'sell';
    
    signalDiv.classList.add(signalClass);

    signalDiv.innerHTML = `<strong>${verdict}</strong> по ${pair} (Бики: ${score}%)`;
    
    liveSignalsContainer.prepend(signalDiv);
    
    setTimeout(() => {
        signalDiv.classList.add('fade-out');
        setTimeout(() => signalDiv.remove(), 500);
    }, 15000);
}

function createPairButton(pair) {
    return `<div class="pair-item">
        <button class="pair-button" data-pair="${pair}">${pair}</button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(data, query = '') {
    let html = '';
    const queryLower = query.toLowerCase();

    function createSection(title, pairs) {
        if (!Array.isArray(pairs)) return '';
        const filteredPairs = pairs.filter(p => p.toLowerCase().includes(queryLower));
        if (filteredPairs.length === 0) return '';

        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        filteredPairs.forEach(pair => sectionHtml += createPairButton(pair));
        sectionHtml += '</div></div>';
        return sectionHtml;
    }
    
    const allKnownPairs = [
        ...(data.forex || []).map(session => session.pairs).flat(),
        ...(data.crypto || []), ...(data.stocks || []), ...(data.commodities || [])
    ];
    let watchlistDisplay = currentWatchlist.map(p_normalized => {
        return allKnownPairs.find(p_display => p_display.replace(/\//g, '') === p_normalized) || p_normalized;
    });

    if (queryLower) {
        watchlistDisplay = watchlistDisplay.filter(p => p.toLowerCase().includes(queryLower));
    }

    if (watchlistDisplay.length > 0) {
        html += createSection('⭐ Обране', watchlistDisplay);
    }
    
    if (Array.isArray(data.forex)) {
        data.forex.forEach(session => {
            const filteredSessionPairs = session.pairs.filter(p => p.toLowerCase().includes(queryLower));
            if (filteredSessionPairs.length > 0) {
                 html += createSection(session.title, filteredSessionPairs);
            }
        });
    }

    listsContainer.innerHTML = html;
    
    listsContainer.querySelectorAll('.pair-button').forEach(button => {
        button.addEventListener('click', (event) => {
            const pair = event.target.dataset.pair;
            debouncedFetchSignal(pair);
        });
    });
}

function renderFavoriteButton(pair) {
    const pairNormalized = pair.replace(/\//g, '');
    const isFavorite = currentWatchlist.includes(pairNormalized);
    const icon = isFavorite ? '✅' : '⭐';
    return `<button class="fav-btn" onclick="toggleFavorite(event, this, '${pair}')">${icon}</button>`;
}

function toggleFavorite(event, button, pair) {
    event.stopPropagation();
    const isCurrentlyFavorite = button.innerHTML.includes('✅');
    const initDataString = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    const url = `${API_BASE_URL}/api/toggle_watchlist?pair=${pair}${initDataString}`;
    
    button.innerHTML = isCurrentlyFavorite ? '⭐' : '✅';

    fetch(url)
        .then(res => res.json())
        .then(data => {
            if (!data.success) {
                button.innerHTML = isCurrentlyFavorite ? '✅' : '⭐';
            } else {
                const pairNormalized = pair.replace(/\//g, '');
                if (isCurrentlyFavorite) {
                    currentWatchlist = currentWatchlist.filter(p => p !== pairNormalized);
                } else {
                    currentWatchlist.push(pairNormalized);
                }
            }
        });
}

// --- ПОЧАТОК ЗМІН: Повністю переписана функція fetchSignal ---
function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую дані для ${pair}...`;
    signalOutput.style.textAlign = 'left';
    
    const initDataQuery = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentTimeframe}${initDataQuery.replace('?', '&')}`;
    
    fetch(signalApiUrl)
        .then(res => {
            // Перевіряємо, чи відповідь успішна. Якщо ні - одразу переходимо до .catch
            if (!res.ok) {
                return res.json().then(errData => { throw new Error(errData.error || `HTTP ${res.status}`) });
            }
            return res.json();
        })
        .then(signalData => {
            // Цей блок виконається тільки для успішних відповідей (200 OK)
            let html = formatSignalAsHtml(signalData);
            signalOutput.innerHTML = html;
        })
        .catch(err => {
            // Цей блок "зловить" усі помилки: і мережеві, і 404, і 500
            signalOutput.innerHTML = `❌ Помилка: ${err.message}`;
        })
        .finally(() => {
            // Цей блок виконається завжди, і в ньому ми ховаємо завантажувач
            showLoader(false);
        });
}

function formatSignalAsHtml(signalData) {
    let html = '';
    if (signalData.special_warning) {
        html += `<div class="special-warning">${signalData.special_warning}</div>`;
    }

    const pair = signalData.pair || 'N/A';
    const price = signalData.price || 0;
    const verdict = signalData.verdict_text || 'Не вдалося визначити.';
    const score = signalData.bull_percentage || 50;
    
    const priceStr = price.toFixed(5);
    html += `
        <div class="signal-header">
            <strong>${pair} (${currentTimeframe})</strong> | Ціна: <code>${priceStr}</code>
        </div>
        <div class="verdict">${verdict}</div>
        <div class="power-balance">
            <span>🐂 Бики: ${score}%</span>
            <span>🐃 Ведмеді: ${100 - score}%</span>
        </div>
    `;

    if (signalData.reasons && signalData.reasons.length > 0) {
        html += '<div class="reasons"><strong>Ключові фактори:</strong><ul>';
        signalData.reasons.forEach(r => { html += `<li>${r}</li>`; });
        html += '</ul></div>';
    }
    return html;
}
// --- КІНЕЦЬ ЗМІН ---

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