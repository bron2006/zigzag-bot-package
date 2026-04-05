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
    
    fetch(`${API_BASE_URL}/api/get_pairs${initDataQuery}`)
        .then(res => res.json())
        .then(staticData => {
            allData = staticData;
            currentWatchlist = (staticData.watchlist || []).map(p => p.replace(/\//g, ''));
            populateLists(allData);
            showLoader(false);
        }).catch(err => {
            console.error("Pairs load error:", err);
            showLoader(false);
        });

    fetch(`${API_BASE_URL}/api/scanner/status${initDataQuery}`)
        .then(res => res.json())
        .then(state => updateScannerButtons(state));

    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data && !data._ping) {
            displayLiveSignal(data);
        }
    };

    scannerControls.addEventListener('click', (event) => {
        const button = event.target.closest('.scanner-button');
        if (!button) return;
        const category = button.dataset.cat;
        fetch(`${API_BASE_URL}/api/scanner/toggle?category=${category}${initDataQuery.replace('?','&')}`)
            .then(res => res.json())
            .then(newState => updateScannerButtons(newState));
    });

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
    const typeClass = signalData.verdict_text === "BUY" ? 'buy' : (signalData.verdict_text === "SELL" ? 'sell' : 'neutral');
    signalDiv.classList.add(typeClass);
    signalDiv.innerHTML = `<div class="live-signal-content" style="text-align:center;"><strong>${signalData.pair}</strong>: ${signalData.verdict_text} (${signalData.score}%)</div><div class="live-signal-timer"></div>`;
    signalDiv.onclick = () => {
        signalOutput.innerHTML = formatSignalAsHtml(signalData, currentExpiration);
        signalContainer.scrollIntoView({ behavior: 'smooth' });
        signalDiv.remove();
    };
    liveSignalsContainer.prepend(signalDiv);
    setTimeout(() => { if (signalDiv.parentElement) signalDiv.remove(); }, 15000);
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
            sHtml += `<div class="pair-item"><button class="pair-button" data-pair="${pair}"><span>${pair}</span></button><button class="fav-btn" onclick="toggleFavorite(event, this, '${pair}')">${isFav ? '✅' : '⭐'}</button></div>`;
        });
        return sHtml + '</div></div>';
    }

    const allP = [
        ...(data.forex ? data.forex.map(s => s.pairs).flat() : []),
        ...(data.crypto || []),
        ...(data.stocks || []),
        ...(data.commodities || [])
    ];

    if (currentWatchlist.length > 0) {
        let wl = currentWatchlist.map(pn => allP.find(p => p.replace(/\//g, '') === pn) || pn);
        html += createSection('⭐ Обране', wl);
    }

    if (data.forex) data.forex.forEach(s => { html += createSection(s.title, s.pairs); });
    if (data.crypto) html += createSection('💎 Криптовалюти', data.crypto);
    if (data.commodities) html += createSection('🥇 Сировина', data.commodities);
    if (data.stocks) html += createSection('📈 Акції/Індекси', data.stocks);

    listsContainer.innerHTML = html;
    listsContainer.querySelectorAll('.pair-button').forEach(btn => {
        btn.addEventListener('click', (e) => debouncedFetchSignal(e.currentTarget.dataset.pair));
    });
}

function toggleFavorite(event, button, pair) {
    event.stopPropagation();
    const iData = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    const pn = pair.replace(/\//g, '');
    
    fetch(`${API_BASE_URL}/api/toggle_watchlist?pair=${pair}${iData}`)
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                if (currentWatchlist.includes(pn)) currentWatchlist = currentWatchlist.filter(p => p !== pn);
                else currentWatchlist.push(pn);
                populateLists(allData, document.getElementById('searchInput').value);
            }
        });
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `<div style="text-align:center; padding:20px;">⏳ Аналіз ${pair}...</div>`;
    const iDataQuery = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${iDataQuery}`)
        .then(res => res.json())
        .then(data => {
            signalOutput.innerHTML = formatSignalAsHtml(data, currentExpiration);
            setTimeout(() => { signalContainer.scrollIntoView({ behavior: 'smooth' }); }, 100);
        })
        .finally(() => showLoader(false));
}

function formatSignalAsHtml(signalData, exp) {
    if (!signalData || signalData.error) return `<div style="text-align:center; color:#ef5350; padding:20px;">❌ Помилка: ${signalData?.error || 'Немає даних'}</div>`;
    const { pair, price, verdict_text, score, sentiment, reasons } = signalData;
    
    let arrow = "↔️", cClass = "neutral";
    if (verdict_text === "BUY") { arrow = "⬆️"; cClass = "buy"; }
    else if (verdict_text === "SELL") { arrow = "⬇️"; cClass = "sell"; }

    return `
        <div class="signal-header" style="text-align:center; font-size:1.2em; margin-bottom:15px;">
            <strong>${pair}</strong> <span style="color:#64748b; font-size:0.8em;">(Exp: ${exp})</span>
        </div>
        <div class="verdict-container" style="text-align:center; margin:20px 0;">
            <div class="arrow" style="font-size:95px; line-height:1; display:block;">${arrow}</div>
            <div class="v-text ${cClass}" style="font-size:42px; font-weight:900; display:block;">${verdict_text}</div>
            <div style="font-size:24px; color:#3390ec; font-family:monospace; margin-top:10px; display:block;">${price ? price.toFixed(5) : 'N/A'}</div>
        </div>
        ${sentiment ? `<div class="ai-verdict" style="padding:10px; border-radius:8px; text-align:center; font-weight:bold; margin:10px auto; border:1px solid; background:rgba(0,0,0,0.1); color:${sentiment==='GO'?'#26a69a':'#ef5350'}; width:fit-content;">${sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${sentiment}</div>` : ""}
        <div class="power-balance" style="display:flex; justify-content:space-around; margin:15px 0; font-weight:bold; text-align:center;">
            <span style="color:#26a69a;">🐂 ${score}%</span>
            <span style="color:#ef5350;">🐃 ${100-score}%</span>
        </div>
        ${reasons && reasons.length ? `<div class="reasons" style="text-align:left; margin-top:15px; border-top:1px solid rgba(255,255,255,0.1); padding-top:10px;">${reasons.map(r => `<div style="margin-bottom:5px;">• ${r}</div>`).join('')}</div>` : ''}
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
