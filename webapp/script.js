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
    fetch(`${API_BASE_URL}/api/get_pairs${initDataQuery}`)
        .then(res => res.json())
        .then(staticData => {
            allData = staticData;
            currentWatchlist = (staticData.watchlist || []).map(p => p.replace(/\//g, ''));
            populateLists(allData);
            showLoader(false);
        }).catch(() => showLoader(false));

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

function displayLiveSignal(signalData) {
    const signalId = `signal-${signalData.pair.replace('/', '')}-${Date.now()}`;
    const signalDiv = document.createElement('div');
    signalDiv.className = 'live-signal';
    signalDiv.onclick = () => {
        signalOutput.innerHTML = formatSignalAsHtml(signalData, currentExpiration);
        signalContainer.scrollIntoView({ behavior: 'smooth' }); // ПОВЕРНУТО СКРОЛ
    };
    liveSignalsContainer.prepend(signalDiv);
}

function createPairButton(pair) {
    return `<div class="pair-item"><button class="pair-button" data-pair="${pair}"><span>${pair}</span></button>${renderFavoriteButton(pair)}</div>`;
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
    const iData = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/toggle_watchlist?pair=${pair}${iData}`).then(() => {
        const pn = pair.replace(/\//g, '');
        if (currentWatchlist.includes(pn)) currentWatchlist = currentWatchlist.filter(p => p !== pn);
        else currentWatchlist.push(pn);
        populateLists(allData, document.getElementById('searchInput').value);
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
        .then(data => { 
            signalOutput.innerHTML = formatSignalAsHtml(data, exp);
            setTimeout(() => { signalContainer.scrollIntoView({ behavior: 'smooth' }); }, 100); // ПОВЕРНУТО СКРОЛ
        })
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
