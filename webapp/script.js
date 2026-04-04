const API_BASE_URL = window.API_BASE_URL || "https://fallback.example.com";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const scannerControls = document.getElementById('scannerControls');
const liveSignalsContainer = document.getElementById('liveSignalsContainer');
const signalContainer = document.getElementById('signalContainer');

let tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

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
    
    fetch(staticPairsUrl)
        .then(res => res.json())
        .then(staticData => {
            allData = staticData;
            currentWatchlist = (staticData.watchlist || []).map(p => p.replace(/\//g, ''));
            populateLists(allData);
            showLoader(false);
        }).catch(err => {
            signalOutput.innerHTML = `<h3 style="color: #ef5350;">❌ Помилка завантаження списків пар.</h3>`;
            showLoader(false);
        });

    fetch(`${API_BASE_URL}/api/scanner/status${initDataQuery}`)
        .then(res => res.json())
        .then(data => updateScannerButtons(data));

    scannerControls.addEventListener('click', (event) => {
        const button = event.target.closest('.scanner-button');
        if (!button) return;
        const category = button.dataset.cat;
        const toggleUrl = `${API_BASE_URL}/api/scanner/toggle?category=${category}${initDataQuery.replace('?','&')}`;
        
        const tempState = {};
        scannerControls.querySelectorAll('.scanner-button').forEach(btn => {
            const cat = btn.dataset.cat;
            tempState[cat] = btn.classList.contains('enabled');
        });
        tempState[category] = !tempState[category];
        updateScannerButtons(tempState);

        fetch(toggleUrl, { method: 'POST' }).then(res => res.json()).then(newState => updateScannerButtons(newState));
    });

    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    eventSource.onmessage = function(event) {
        const signalData = JSON.parse(event.data);
        if (signalData._ping) return;

        // --- ОСЬ ЦЕ Я ДОДАВ: ОНОВЛЕННЯ ЦІНИ НА КНОПЦІ В РЕАЛЬНОМУ ЧАСІ ---
        if (signalData.pair && signalData.price) {
            const pId = signalData.pair.replace(/\//g, "");
            const el = document.getElementById(`price-${pId}`);
            if (el) {
                el.textContent = signalData.price.toFixed(5);
                el.style.color = "#00ff00"; // Зелений спалах
                setTimeout(() => { el.style.color = "#3390ec"; }, 300);
            }
        }

        displayLiveSignal(signalData);
    };
    eventSource.onerror = function(err) { console.error("EventSource failed:", err); };

    const expirationButtons = document.querySelectorAll('.tf-button');
    expirationButtons.forEach(button => {
        button.addEventListener('click', () => {
            expirationButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            currentExpiration = button.dataset.exp;
            if(lastSelectedPair) {
                fetchSignal(lastSelectedPair);
            }
        });
    });

    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', debounce((event) => { populateLists(allData, event.target.value); }, 300));
});

function updateScannerButtons(stateDict) {
    const textMap = { forex: "💹 Forex", crypto: "💎 Crypto", commodities: "🥇 Сировина", watchlist: "⭐ Обране" };
    for (const category in textMap) {
        const button = scannerControls.querySelector(`.scanner-button[data-cat="${category}"]`);
        if (button) {
            const isEnabled = stateDict[category];
            const icon = isEnabled ? '✅' : '❌';
            button.textContent = `${icon} ${textMap[category]}`;
            button.classList.toggle('enabled', isEnabled);
        }
    }
}

function displayLiveSignal(signalData) {
    const signalId = `signal-${signalData.pair.replace('/', '')}-${Date.now()}`;
    const signalDiv = document.createElement('div');
    signalDiv.id = signalId;
    signalDiv.className = 'live-signal';
    signalDiv.style.cursor = 'pointer';
    
    signalDiv.onclick = () => {
        const expiration = document.querySelector('#expirationSelector .tf-button.active')?.dataset.exp || '5m';
        signalOutput.innerHTML = formatSignalAsHtml(signalData, expiration);
        signalContainer.scrollIntoView({ behavior: 'smooth' });
    };

    const verdict = signalData.verdict_text || '...';
    const pair = signalData.pair || 'N/A';
    const score = signalData.score || 50;
    
    let signalClass = 'neutral';
    if (score >= 65) signalClass = 'buy';
    if (score <= 35) signalClass = 'sell';
    
    signalDiv.classList.add(signalClass);
    signalDiv.innerHTML = `<div class="live-signal-content">${verdict} по ${pair} (Оцінка: ${score})</div><button class="live-signal-close" onclick="event.stopPropagation(); this.parentElement.remove()">×</button>`;
    
    liveSignalsContainer.prepend(signalDiv);

    setTimeout(() => {
        const el = document.getElementById(signalId);
        if (el) {
            el.classList.add('fade-out');
            setTimeout(() => el.remove(), 500);
        }
    }, 300000);
}

// --- ОСЬ ЦЕ Я МОДИФІКУВАВ: ДОДАНО ID ДЛЯ ЦІНИ ---
function createPairButton(pair) {
    const pId = pair.replace(/\//g, "");
    return `<div class="pair-item">
        <button class="pair-button" data-pair="${pair}" style="display:flex; justify-content:space-between; align-items:center;">
            <span>${pair}</span>
            <span id="price-${pId}" style="font-family:monospace; color:#3390ec; font-size:0.85em; background:rgba(0,0,0,0.2); padding:2px 5px; border-radius:4px;">---</span>
        </button>
        ${renderFavoriteButton(pair)}
    </div>`;
}

function populateLists(data, query = '') {
    let html = '';
    const queryLower = query.toLowerCase();

    function createSection(title, pairs) {
        if (!Array.isArray(pairs) || pairs.length === 0) return '';
        const filteredPairs = pairs.filter(p => p.toLowerCase().includes(queryLower));
        if (filteredPairs.length === 0) return '';
        
        let sectionHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        filteredPairs.forEach(pair => sectionHtml += createPairButton(pair));
        sectionHtml += '</div></div>';
        return sectionHtml;
    }
    
    const allKnownPairs = [...(data.forex || []).map(session => session.pairs).flat(), ...(data.crypto || []), ...(data.stocks || []), ...(data.commodities || [])];
    let watchlistDisplay = currentWatchlist.map(p_normalized => allKnownPairs.find(p_display => p_display.replace(/\//g, '') === p_normalized) || p_normalized);
    
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

    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);

    listsContainer.innerHTML = html;
    listsContainer.querySelectorAll('.pair-button').forEach(button => {
        button.addEventListener('click', (event) => {
            const pair = event.currentTarget.dataset.pair;
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
                const currentQuery = document.getElementById('searchInput').value;
                populateLists(allData, currentQuery);
            }
        });
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    signalOutput.style.textAlign = 'left';

    const activeBtn = document.querySelector('#expirationSelector .tf-button.active');
    const expiration = activeBtn ? activeBtn.dataset.exp : '1m';
    
    const initDataQuery = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${expiration}${initDataQuery.replace('?', '&')}`;

    fetch(signalApiUrl)
        .then(res => {
            if (!res.ok) {
                return res.json().then(errData => { throw new Error(errData.error || `HTTP ${res.status}`) });
            }
            return res.json();
        })
        .then(signalData => {
            let html = formatSignalAsHtml(signalData, expiration);
            signalOutput.innerHTML = html;
            setTimeout(() => { signalContainer.scrollIntoView({ behavior: 'smooth' }); }, 150);
        })
        .catch(err => {
            signalOutput.innerHTML = `❌ Помилка: ${err.message}`;
        })
        .finally(() => {
            showLoader(false);
        });
}

function formatSignalAsHtml(signalData, expiration) {
    if (!signalData || Object.keys(signalData).length === 0) return "Немає даних для відображення.";
    if (signalData.error) return `❌ Помилка: ${signalData.error}`;

    const { pair, price, verdict_text, reasons, score, sentiment } = signalData;
    const priceStr = price ? price.toFixed(5) : "N/A";

    let priceClass = 'price-neutral';
    if (score >= 65) priceClass = 'price-call';
    if (score <= 35) priceClass = 'price-put';

    let reasonsHtml = '';
    if (reasons && reasons.length > 0) {
        reasonsHtml = '<div class="reasons"><strong>Ключові фактори:</strong><ul>';
        reasons.forEach(r => { reasonsHtml += `<li>${r}</li>`; });
        reasonsHtml += '</ul></div>';
    }

    const aiHtml = sentiment ? `<div class="ai-verdict ${sentiment==='GO'?'ai-go':'ai-block'}" style="padding:10px; border-radius:8px; text-align:center; font-weight:bold; margin:10px 0; border:1px solid; background:rgba(0,0,0,0.1); color:${sentiment==='GO'?'#26a69a':'#ef5350'}">${sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${sentiment}</div>` : "";

    return `
        <div class="signal-header">
            <strong>${pair} (Експірація: ${expiration})</strong>
        </div>

        <div class="price-display-manual">
            <div class="price-label">Ціна входу</div>
            <div class="signal-price ${priceClass}">${priceStr}</div>
        </div>
        
        <div class="verdict">${verdict_text}</div>
        
        ${aiHtml}

        <div class="power-balance">
            <span>🐂 Бики: ${score}%</span>
            <span>🐃 Ведмеді: ${100 - score}%</span>
        </div>
        
        ${reasonsHtml}
    `;
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