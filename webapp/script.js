const API_BASE_URL = window.API_BASE_URL || "";
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
    
    // 1. Завантаження списків
    fetch(`${API_BASE_URL}/api/get_pairs${initDataQuery}`)
        .then(res => res.json())
        .then(staticData => {
            allData = staticData;
            currentWatchlist = (staticData.watchlist || []).map(p => p.replace(/\//g, ''));
            populateLists(allData);
            showLoader(false);
        }).catch(() => showLoader(false));

    // 2. Статус сканерів
    fetch(`${API_BASE_URL}/api/scanner/status${initDataQuery}`)
        .then(res => res.json())
        .then(state => updateScannerButtons(state));

    // 3. ПІДКЛЮЧЕННЯ ЖИВИХ СИГНАЛІВ (SSE)
    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data && !data._ping) {
            console.log("Новий живий сигнал:", data);
            displayLiveSignal(data);
        }
    };

    eventSource.onerror = function() {
        console.log("SSE error, reconnecting...");
    };

    // Обробка кнопок сканера
    scannerControls.addEventListener('click', (event) => {
        const button = event.target.closest('.scanner-button');
        if (!button) return;
        const category = button.dataset.cat;
        fetch(`${API_BASE_URL}/api/scanner/toggle?category=${category}${initDataQuery.replace('?','&')}`)
            .then(res => res.json())
            .then(newState => updateScannerButtons(newState));
    });

    // Експірація
    const expirationButtons = document.querySelectorAll('.tf-button');
    expirationButtons.forEach(button => {
        button.addEventListener('click', () => {
            expirationButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            currentExpiration = button.dataset.exp;
            if(lastSelectedPair) fetchSignal(lastSelectedPair);
        });
    });

    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', debounce((e) => populateLists(allData, e.target.value), 300));
});

function updateScannerButtons(stateDict) {
    if (!stateDict) return;
    const textMap = { forex: "Forex", crypto: "Crypto", commodities: "Сировина", watchlist: "Обране" };
    Object.keys(textMap).forEach(cat => {
        const btn = scannerControls.querySelector(`.scanner-button[data-cat="${cat}"]`);
        if (btn) {
            const isEnabled = stateDict[cat] === true;
            btn.textContent = `${isEnabled ? '✅' : '❌'} ${textMap[cat]}`;
            btn.classList.toggle('enabled', isEnabled);
        }
    });
}

function displayLiveSignal(signalData) {
    const signalDiv = document.createElement('div');
    signalDiv.className = 'live-signal';
    
    const score = signalData.score || 50;
    const typeClass = score >= 65 ? 'buy' : (score <= 35 ? 'sell' : 'neutral');
    signalDiv.classList.add(typeClass);

    signalDiv.innerHTML = `
        <div class="live-signal-content">
            <strong>${signalData.pair}</strong>: ${signalData.verdict_text} (${score}%)
        </div>
        <div class="live-signal-timer"></div>
    `;

    signalDiv.onclick = () => {
        signalOutput.innerHTML = formatSignalAsHtml(signalData, currentExpiration);
        signalContainer.scrollIntoView({ behavior: 'smooth' });
        signalDiv.remove();
    };

    liveSignalsContainer.prepend(signalDiv);

    // Видаляємо через 15 секунд
    setTimeout(() => {
        if (signalDiv.parentElement) {
            signalDiv.style.opacity = '0';
            signalDiv.style.transform = 'translateX(100px)';
            setTimeout(() => signalDiv.remove(), 500);
        }
    }, 15000);
}

function populateLists(data, query = '') {
    let html = '';
    const queryLower = query.toLowerCase();
    function createSection(title, pairs) {
        if (!Array.isArray(pairs)) return '';
        const fps = pairs.filter(p => p.toLowerCase().includes(queryLower));
        if (fps.length === 0) return '';
        let sHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        fps.forEach(pair => {
            const pn = pair.replace(/\//g, '');
            const isFav = currentWatchlist.includes(pn);
            sHtml += `
                <div class="pair-item">
                    <button class="pair-button" data-pair="${pair}"><span>${pair}</span></button>
                    <button class="fav-btn" onclick="toggleFavorite(event, this, '${pair}')">${isFav ? '✅' : '⭐'}</button>
                </div>`;
        });
        return sHtml + '</div></div>';
    }
    if (data.forex) data.forex.forEach(s => html += createSection(s.title, s.pairs));
    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);
    listsContainer.innerHTML = html;
    listsContainer.querySelectorAll('.pair-button').forEach(btn => {
        btn.addEventListener('click', (e) => debouncedFetchSignal(e.currentTarget.dataset.pair));
    });
}

function toggleFavorite(event, button, pair) {
    event.stopPropagation();
    const iData = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/toggle_watchlist?pair=${pair}${iData}`)
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                const pn = pair.replace(/\//g, '');
                if (currentWatchlist.includes(pn)) currentWatchlist = currentWatchlist.filter(p => p !== pn);
                else currentWatchlist.push(pn);
                populateLists(allData, document.getElementById('searchInput').value);
            }
        });
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    const initDataQuery = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${initDataQuery}`)
        .then(res => res.json())
        .then(data => {
            signalOutput.innerHTML = formatSignalAsHtml(data, currentExpiration);
            setTimeout(() => { signalContainer.scrollIntoView({ behavior: 'smooth' }); }, 100);
        })
        .catch(() => signalOutput.innerHTML = "❌ Помилка завантаження")
        .finally(() => showLoader(false));
}

function formatSignalAsHtml(signalData, exp) {
    if (!signalData || signalData.error) return `❌ Помилка: ${signalData?.error || 'Немає даних'}`;
    const { pair, price, verdict_text, score, sentiment, reasons } = signalData;
    let arrow = "↔️", cClass = "neutral";
    if (score >= 65) { arrow = "⬆️"; cClass = "buy"; }
    else if (score <= 35) { arrow = "⬇️"; cClass = "sell"; }

    return `
        <div class="signal-header"><strong>${pair}</strong> (Exp: ${exp})</div>
        <div class="verdict-container">
            <div class="arrow" style="font-size:95px;">${arrow}</div>
            <div class="v-text ${cClass}" style="font-size:42px;">${verdict_text}</div>
            <div class="price">${price ? price.toFixed(5) : 'N/A'}</div>
        </div>
        ${sentiment ? `<div class="ai-verdict" style="padding:10px; border-radius:8px; text-align:center; font-weight:bold; margin:10px 0; border:1px solid; background:rgba(0,0,0,0.1); color:${sentiment==='GO'?'#26a69a':'#ef5350'}">${sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${sentiment}</div>` : ""}
        <div class="power-balance">🐂 ${score}% | 🐃 ${100-score}%</div>
        ${reasons && reasons.length ? '<div class="reasons"><ul>' + reasons.map(r => `<li>${r}</li>`).join('') + '</ul></div>' : ''}
    `;
}

function showLoader(visible) { loader.className = visible ? '' : 'hidden'; }
function debounce(func, delay) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), delay);
    };
}
