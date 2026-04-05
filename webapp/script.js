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
            signalOutput.innerHTML = `<h3>❌ Помилка завантаження</h3>`;
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
            tempState[btn.dataset.cat] = btn.classList.contains('enabled');
        });
        tempState[category] = !tempState[category];
        updateScannerButtons(tempState);
        fetch(toggleUrl, { method: 'POST' }).then(res => res.json()).then(newState => updateScannerButtons(newState));
    });

    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    eventSource.onmessage = function(event) {
        const signalData = JSON.parse(event.data);
        if (signalData._ping) return;
        if (signalData.pair && signalData.price) {
            const pId = signalData.pair.replace(/\//g, "");
            const el = document.getElementById(`price-${pId}`);
            if (el) {
                el.textContent = signalData.price.toFixed(5);
                el.style.color = "#00ff00";
                setTimeout(() => { el.style.color = "#3390ec"; }, 300);
            }
        }
        displayLiveSignal(signalData);
    };

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
    searchInput.addEventListener('input', debounce((event) => { populateLists(allData, event.target.value); }, 300));
});

function updateScannerButtons(stateDict) {
    const textMap = { forex: "💹 Forex", crypto: "💎 Crypto", commodities: "🥇 Сировина", watchlist: "⭐ Обране" };
    for (const category in textMap) {
        const button = scannerControls.querySelector(`.scanner-button[data-cat="${category}"]`);
        if (button) {
            const isEnabled = stateDict[category];
            button.textContent = `${isEnabled ? '✅' : '❌'} ${textMap[category]}`;
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
        signalOutput.innerHTML = formatSignalAsHtml(signalData, currentExpiration);
        signalContainer.scrollIntoView({ behavior: 'smooth' });
    };
    const score = signalData.score || 50;
    signalDiv.classList.add(score >= 65 ? 'buy' : (score <= 35 ? 'sell' : 'neutral'));
    signalDiv.innerHTML = `<div class="live-signal-content">${signalData.verdict_text} по ${signalData.pair} (${score}%)</div><button class="live-signal-close" onclick="event.stopPropagation(); this.parentElement.remove()">×</button>`;
    liveSignalsContainer.prepend(signalDiv);
    setTimeout(() => { const el = document.getElementById(signalId); if (el) el.remove(); }, 300000);
}

function createPairButton(pair) {
    const pId = pair.replace(/\//g, "");
    return `<div class="pair-item"><button class="pair-button" data-pair="${pair}" style="display:flex; justify-content:space-between; align-items:center;"><span>${pair}</span><span id="price-${pId}" style="font-family:monospace; color:#3390ec; font-size:0.85em; background:rgba(0,0,0,0.2); padding:2px 5px; border-radius:4px;">---</span></button>${renderFavoriteButton(pair)}</div>`;
}

function populateLists(data, query = '') {
    let html = '';
    const queryLower = query.toLowerCase();
    function createSection(title, pairs) {
        if (!Array.isArray(pairs)) return '';
        const fps = pairs.filter(p => p.toLowerCase().includes(queryLower));
        if (fps.length === 0) return '';
        let sHtml = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        fps.forEach(pair => sHtml += createPairButton(pair));
        return sHtml + '</div></div>';
    }
    const allP = [...(data.forex || []).map(s => s.pairs).flat(), ...(data.crypto || []), ...(data.stocks || []), ...(data.commodities || [])];
    let wl = currentWatchlist.map(p => allP.find(pd => pd.replace(/\//g, '') === p) || p);
    if (queryLower) wl = wl.filter(p => p.toLowerCase().includes(queryLower));
    if (wl.length > 0) html += createSection('⭐ Обране', wl);
    if (data.forex) data.forex.forEach(s => html += createSection(s.title, s.pairs));
    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);
    listsContainer.innerHTML = html;
    listsContainer.querySelectorAll('.pair-button').forEach(btn => btn.addEventListener('click', (e) => debouncedFetchSignal(e.currentTarget.dataset.pair)));
}

function renderFavoriteButton(pair) {
    const pn = pair.replace(/\//g, '');
    return `<button class="fav-btn" onclick="toggleFavorite(event, this, '${pair}')">${currentWatchlist.includes(pn) ? '✅' : '⭐'}</button>`;
}

function toggleFavorite(event, button, pair) {
    event.stopPropagation();
    const isFav = button.innerHTML.includes('✅');
    const iData = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    button.innerHTML = isFav ? '⭐' : '✅';
    fetch(`${API_BASE_URL}/api/toggle_watchlist?pair=${pair}${iData}`).then(res => res.json()).then(data => {
        if (data.success) {
            const pn = pair.replace(/\//g, '');
            if (isFav) currentWatchlist = currentWatchlist.filter(p => p !== pn);
            else currentWatchlist.push(pn);
            populateLists(allData, document.getElementById('searchInput').value);
        } else button.innerHTML = isFav ? '✅' : '⭐';
    });
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    const exp = document.querySelector('#expirationSelector .tf-button.active')?.dataset.exp || '1m';
    const iData = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${exp}${iData.replace('?', '&')}`)
        .then(res => res.json())
        .then(data => { signalOutput.innerHTML = formatSignalAsHtml(data, exp); })
        .catch(err => { signalOutput.innerHTML = `❌ Помилка: ${err.message}`; })
        .finally(() => showLoader(false));
}

function formatSignalAsHtml(signalData, exp) {
    if (!signalData || signalData.error) return `❌ Помилка: ${signalData?.error || 'Немає даних'}`;
    const { pair, price, verdict_text, reasons, score, sentiment } = signalData;
    const pStr = price ? price.toFixed(5) : "N/A";
    let arrow = "➡️", cClass = "neutral";
    if (score >= 65) { arrow = "⬆️"; cClass = "buy"; }
    else if (score <= 35) { arrow = "⬇️"; cClass = "sell"; }

    return `
        <div class="signal-header" style="text-align:center; font-size:1.2em; margin-bottom:15px;">
            <strong>${pair}</strong> <span style="color:#64748b; font-size:0.8em;">(Exp: ${exp})</span>
        </div>
        <div class="verdict-container" style="text-align:center; margin:20px 0;">
            <div class="arrow" style="font-size:95px; line-height:1;">${arrow}</div>
            <div class="v-text ${cClass}" style="font-size:42px; font-weight:900;">${verdict_text}</div>
            <div style="font-size:24px; color:#3390ec; font-family:monospace; margin-top:10px;">${pStr}</div>
        </div>
        ${sentiment ? `<div class="ai-verdict" style="padding:10px; border-radius:8px; text-align:center; font-weight:bold; margin:10px 0; border:1px solid; background:rgba(0,0,0,0.1); color:${sentiment==='GO'?'#26a69a':'#ef5350'}">${sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${sentiment}</div>` : ""}
        <div class="power-balance" style="display:flex; justify-content:space-around; margin:15px 0; font-weight:bold;">
            <span style="color:#26a69a;">🐂 ${score}%</span>
            <span style="color:#ef5350;">🐃 ${100 - score}%</span>
        </div>
        ${reasons && reasons.length ? '<div class="reasons"><strong>Фактори:</strong><ul>' + reasons.map(r => `<li>${r}</li>`).join('') + '</ul></div>' : ''}
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
