const API_BASE_URL = window.API_BASE_URL || "";
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
        .then(res => res.json()).then(data => {
            allData = data;
            currentWatchlist = (data.watchlist || []).map(p => p.replace(/\//g, ''));
            populateLists(allData);
            showLoader(false);
        }).catch(() => showLoader(false));

    fetch(`${API_BASE_URL}/api/scanner/status${initDataQuery}`).then(res => res.json()).then(data => updateScannerButtons(data));

    // SSE ДЛЯ ЦІН
    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.pair && data.price) {
            const pId = data.pair.replace(/\//g, "");
            const el = document.getElementById(`price-${pId}`);
            if (el) el.textContent = data.price.toFixed(5);
        }
        if (data.verdict_text) displayLiveSignal(data);
    };

    document.querySelectorAll('.tf-button').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tf-button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentExpiration = btn.dataset.exp;
            if(lastSelectedPair) fetchSignal(lastSelectedPair);
        });
    });

    document.getElementById('searchInput').addEventListener('input', debounce((e) => { populateLists(allData, e.target.value); }, 300));
});

function populateLists(data, query = '') {
    let html = '';
    const qL = query.toLowerCase();
    const createSection = (title, pairs) => {
        if (!Array.isArray(pairs) || pairs.length === 0) return '';
        const filtered = pairs.filter(p => p.toLowerCase().includes(qL));
        if (filtered.length === 0) return '';
        let s = `<div class="category"><div class="category-title">${title}</div><div class="pair-list">`;
        filtered.forEach(p => {
            const pId = p.replace(/\//g, "");
            s += `<div class="pair-item"><button class="pair-button" data-pair="${p}" style="display:flex; justify-content:space-between; width:100%; padding:10px;"><span>${p}</span><span id="price-${pId}" style="font-family:monospace; color:#3390ec;">---</span></button><button class="fav-btn" onclick="toggleFavorite(event, this, '${p}')">${currentWatchlist.includes(pId) ? '✅' : '⭐'}</button></div>`;
        });
        return s + '</div></div>';
    };
    const all = [...(data.forex || []).map(s => s.pairs).flat(), ...(data.crypto || []), ...(data.stocks || []), ...(data.commodities || [])];
    let watch = currentWatchlist.map(p_n => all.find(p_d => p_d.replace(/\//g, '') === p_n) || p_n);
    if (qL) watch = watch.filter(p => p.toLowerCase().includes(qL));
    if (watch.length > 0) html += createSection('⭐ Обране', watch);
    if (data.forex) data.forex.forEach(s => html += createSection(s.title, s.pairs));
    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);
    listsContainer.innerHTML = html;
    listsContainer.querySelectorAll('.pair-button').forEach(b => b.addEventListener('click', (e) => debouncedFetchSignal(e.currentTarget.dataset.pair)));
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    const q = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${q}`)
        .then(res => res.json()).then(d => {
            signalOutput.innerHTML = formatSignalAsHtml(d, currentExpiration);
            setTimeout(() => { signalOutput.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 150);
        }).finally(() => showLoader(false));
}

function formatSignalAsHtml(d, exp) {
    if (d.error) return `❌ Помилка: ${d.error}`;
    const score = d.score || 50;
    const ai = d.sentiment ? `<div class="ai-verdict ${d.sentiment==='GO'?'ai-go':'ai-block'}" style="padding:10px; border-radius:8px; text-align:center; font-weight:bold; margin:10px 0; border:1px solid; background:rgba(0,0,0,0.2); color:${d.sentiment==='GO'?'#26a69a':'#ef5350'}">${d.sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${d.sentiment}</div>` : "";
    return `<div class="signal-header"><strong>${d.pair} (${exp})</strong></div><div class="price-display-manual"><div class="price-label">Ціна входу</div><div class="signal-price ${score>=65?'price-call':(score<=35?'price-put':'price-neutral')}">${d.price ? d.price.toFixed(5) : "N/A"}</div></div><div class="verdict">${d.verdict_text}</div>${ai}<div class="power-balance"><span>🐂 Бики: ${score}%</span><span>🐃 Ведмеді: ${100 - score}%</span></div>`;
}

function updateScannerButtons(s) { /* код кнопок сканера */ }
function displayLiveSignal(s) { /* код живих сигналів */ }
function toggleFavorite(e, b, p) { /* код обраного */ }
function showLoader(v) { loader.className = v ? '' : 'hidden'; }
function debounce(f, d) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => f.apply(this, a), d); }; }