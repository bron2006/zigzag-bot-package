const API_BASE_URL = window.API_BASE_URL || "https://fallback.example.com";
const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const scannerControls = document.getElementById('scannerControls');
const liveSignalsContainer = document.getElementById('liveSignalsContainer');
const signalContainer = document.getElementById('signalContainer');

let tg = window.Telegram.WebApp;
tg.ready(); tg.expand();

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
            signalOutput.innerHTML = `<h3 style="color: #ef5350;">❌ Помилка завантаження списків пар.</h3>`;
            showLoader(false);
        });

    fetch(`${API_BASE_URL}/api/scanner/status${initDataQuery}`).then(res => res.json()).then(data => updateScannerButtons(data));

    // --- ТУТ ЗМІНА: ОБРОБКА ЖИВИХ ЦІН ---
    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    eventSource.onmessage = function(event) {
        const signalData = JSON.parse(event.data);
        if (signalData._ping) return;
        
        // Оновлюємо ціну на кнопці, якщо вона прийшла
        if (signalData.pair && signalData.price) {
            const pId = signalData.pair.replace(/\//g, "");
            const priceEl = document.getElementById(`price-${pId}`);
            if (priceEl) priceEl.textContent = signalData.price.toFixed(5);
        }
        
        displayLiveSignal(signalData);
    };

    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', debounce((e) => { populateLists(allData, e.target.value); }, 300));
});

// --- ТУТ ЗМІНА: ДОДАНО ID ДЛЯ ЦІНИ В КНОПКУ ---
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
        const filtered = pairs.filter(p => p.toLowerCase().includes(queryLower));
        if (filtered.length === 0) return '';
        let s = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        filtered.forEach(pair => s += createPairButton(pair));
        return s + '</div></div>';
    }
    const allKnown = [...(data.forex || []).map(s => s.pairs).flat(), ...(data.crypto || []), ...(data.stocks || []), ...(data.commodities || [])];
    let watchDisplay = currentWatchlist.map(pN => allKnown.find(pD => pD.replace(/\//g, '') === pN) || pN);
    if (queryLower) watchDisplay = watchDisplay.filter(p => p.toLowerCase().includes(queryLower));
    
    if (watchDisplay.length > 0) html += createSection('⭐ Обране', watchDisplay);
    if (data.forex) data.forex.forEach(s => html += createSection(s.title, s.pairs));
    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);

    listsContainer.innerHTML = html;
    listsContainer.querySelectorAll('.pair-button').forEach(btn => {
        btn.addEventListener('click', (e) => debouncedFetchSignal(e.currentTarget.dataset.pair));
    });
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    const q = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${q.replace('?', '&')}`)
        .then(res => res.json()).then(d => {
            signalOutput.innerHTML = formatSignalAsHtml(d, currentExpiration);
            // АВТОСКРОЛЛ
            setTimeout(() => { signalContainer.scrollIntoView({ behavior: 'smooth' }); }, 100);
        }).finally(() => showLoader(false));
}

function formatSignalAsHtml(d, exp) {
    if (d.error) return `❌ Помилка: ${d.error}`;
    const score = d.score || 50;
    // --- ТУТ ЗМІНА: ДОДАНО ШІ-ВЕРДИКТ ---
    const aiHtml = d.sentiment ? `<div class="ai-verdict ${d.sentiment==='GO'?'ai-go':'ai-block'}" style="padding:10px; border-radius:8px; text-align:center; font-weight:bold; margin:10px 0; border:1px solid; background:rgba(0,0,0,0.1); color:${d.sentiment==='GO'?'#26a69a':'#ef5350'}">${d.sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${d.sentiment}</div>` : "";
    
    return `
        <div class="signal-header"><strong>${d.pair} (${exp})</strong></div>
        <div class="price-display-manual">
            <div class="price-label">Ціна входу</div>
            <div class="signal-price ${score>=65?'price-call':(score<=35?'price-put':'price-neutral')}">${d.price ? d.price.toFixed(5) : "N/A"}</div>
        </div>
        <div class="verdict">${d.verdict_text}</div>
        ${aiHtml}
        <div class="power-balance"><span>🐂 Бики: ${score}%</span><span>🐃 Ведмеді: ${100 - score}%</span></div>
    `;
}

function renderFavoriteButton(pair) {
    const isFav = currentWatchlist.includes(pair.replace(/\//g, ''));
    return `<button class="fav-btn" onclick="toggleFavorite(event, this, '${pair}')">${isFav ? '✅' : '⭐'}</button>`;
}

function toggleFavorite(event, button, pair) {
    event.stopPropagation();
    const isFav = button.innerHTML.includes('✅');
    const q = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/toggle_watchlist?pair=${pair}${q}`).then(res => res.json()).then(d => {
        if (d.success) {
            const pN = pair.replace(/\//g, '');
            if (isFav) currentWatchlist = currentWatchlist.filter(p => p !== pN);
            else currentWatchlist.push(pN);
            populateLists(allData, document.getElementById('searchInput').value);
        }
    });
}

function updateScannerButtons(s) { /* твій код кнопок */ }
function displayLiveSignal(s) { /* твій код сигналів */ }
function showLoader(v) { loader.className = v ? '' : 'hidden'; }
function debounce(f, d) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => f.apply(this, a), d); }; }