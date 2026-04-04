const API_BASE_URL = window.API_BASE_URL || "";
const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const scannerControls = document.getElementById('scannerControls');
const liveSignalsContainer = document.getElementById('liveSignalsContainer');
const signalContainer = document.getElementById('signalContainer');

let tg = window.Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); }

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
        }).catch(() => {
            signalOutput.innerHTML = `<h3 style="color: #ef5350;">❌ Помилка завантаження.</h3>`;
            showLoader(false);
        });

    fetch(`${API_BASE_URL}/api/scanner/status${initDataQuery}`).then(res => res.json()).then(data => updateScannerButtons(data));

    scannerControls.addEventListener('click', (event) => {
        const button = event.target.closest('.scanner-button');
        if (!button) return;
        const category = button.dataset.cat;
        fetch(`${API_BASE_URL}/api/scanner/toggle?category=${category}${initDataQuery.replace('?','&')}`, { method: 'POST' })
            .then(res => res.json()).then(newState => updateScannerButtons(newState));
    });

    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    eventSource.onmessage = (e) => displayLiveSignal(JSON.parse(e.data));

    document.querySelectorAll('.tf-button').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tf-button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentExpiration = btn.dataset.exp;
            if(lastSelectedPair) fetchSignal(lastSelectedPair);
        });
    });

    document.getElementById('searchInput').addEventListener('input', debounce((e) => populateLists(allData, e.target.value), 300));
});

function updateScannerButtons(stateDict) {
    const textMap = { forex: "💹 Forex", crypto: "💎 Крипто", commodities: "🥇 Сировина", watchlist: "⭐ Обране" };
    for (const cat in textMap) {
        const btn = scannerControls.querySelector(`.scanner-button[data-cat="${cat}"]`);
        if (btn) {
            btn.textContent = `${stateDict[cat] ? '✅' : '❌'} ${textMap[cat]}`;
            btn.classList.toggle('enabled', stateDict[cat]);
        }
    }
}

function populateLists(data, query = '') {
    let html = '';
    const q = query.toLowerCase();
    const createSection = (title, pairs) => {
        const filtered = (pairs || []).filter(p => p.toLowerCase().includes(q));
        if (!filtered.length) return '';
        let s = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        filtered.forEach(p => s += `<div class="pair-item"><button class="pair-button" data-pair="${p}">${p}</button><button class="fav-btn" onclick="toggleFavorite(event, this, '${p}')">${currentWatchlist.includes(p.replace(/\//g,'')) ? '✅' : '⭐'}</button></div>`);
        return s + '</div></div>';
    };
    html += createSection('⭐ Обране', currentWatchlist);
    if (data.forex) data.forex.forEach(s => html += createSection(s.title, s.pairs));
    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);
    listsContainer.innerHTML = html;
    listsContainer.querySelectorAll('.pair-button').forEach(b => b.addEventListener('click', (e) => debouncedFetchSignal(e.target.dataset.pair)));
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    const initDataQuery = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${initDataQuery}`)
        .then(res => res.json())
        .then(data => { signalOutput.innerHTML = formatSignalAsHtml(data, currentExpiration); })
        .catch(err => { signalOutput.innerHTML = `❌ Помилка: ${err.message}`; })
        .finally(() => { signalContainer.scrollIntoView({ behavior: 'smooth' }); showLoader(false); });
}

function formatSignalAsHtml(data, exp) {
    if (data.error) return `❌ Помилка: ${data.error}`;
    const { pair, price, verdict_text, score, sentiment } = data;
    const pClass = score >= 65 ? 'price-call' : (score <= 35 ? 'price-put' : 'price-neutral');
    
    let aiHtml = "";
    if (sentiment) {
        const aiClass = sentiment === "GO" ? "ai-go" : "ai-block";
        aiHtml = `<div class="ai-verdict ${aiClass}">${sentiment === "GO" ? "✅" : "🚨"} ШІ Фільтр новин: ${sentiment}</div>`;
    }

    return `
        <div class="signal-header"><strong>${pair} (Експірація: ${exp})</strong></div>
        <div class="price-display-manual"><div class="price-label">Ціна входу</div><div class="signal-price ${pClass}">${price ? price.toFixed(5) : "N/A"}</div></div>
        <div class="verdict">${verdict_text}</div>
        ${aiHtml}
        <div class="power-balance"><span>🐂 Бики: ${score}%</span><span>🐃 Ведмеді: ${100 - score}%</span></div>
    `;
}

function showLoader(v) { loader.className = v ? '' : 'hidden'; }
function debounce(f, d) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => f.apply(this, a), d); }; }