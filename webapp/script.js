const API_BASE_URL = window.API_BASE_URL || "";
const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
let currentWatchlist = [], allData = {}, lastSelectedPair = null, currentExpiration = '1m';
let initData = window.Telegram?.WebApp?.initData || '';

document.addEventListener('DOMContentLoaded', () => {
    showLoader(true);
    const initDataQuery = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/get_pairs${initDataQuery}`)
        .then(res => res.json()).then(data => {
            allData = data;
            currentWatchlist = (data.watchlist || []).map(p => p.replace(/\//g, ''));
            populateLists(data);
            showLoader(false);
        }).catch(() => showLoader(false));

    // SSE ДЛЯ ЖИВИХ ЦІН НА КНОПКАХ
    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initDataQuery}`);
    eventSource.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.pair && data.price) {
            const pId = data.pair.replace(/\//g, "");
            const el = document.getElementById(`price-${pId}`);
            if (el) {
                el.textContent = data.price.toFixed(5);
                el.style.color = "#3390ec"; 
                setTimeout(() => { if(el) el.style.color = ""; }, 500);
            }
        }
    };
});

function populateLists(data) {
    let html = '';
    const createSection = (title, pairs) => {
        if (!pairs || pairs.length === 0) return '';
        let s = `<div class="category-title">${title}</div><div class="pair-list">`;
        pairs.forEach(p => {
            const pId = p.replace(/\//g, "");
            s += `<div class="pair-item">
                <button class="pair-button" onclick="fetchSignal('${p}')">
                    <span>${p}</span><span class="live-price-min" id="price-${pId}">---</span>
                </button>
                <button class="fav-btn">${currentWatchlist.includes(pId) ? '✅' : '⭐'}</button>
            </div>`;
        });
        return s + '</div>';
    };

    if (currentWatchlist.length > 0) html += createSection('⭐ Обране', currentWatchlist);
    if (data.forex) data.forex.forEach(session => html += createSection(session.title, session.pairs));
    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);
    listsContainer.innerHTML = html;
}

function fetchSignal(pair) {
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    const initDataQuery = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${initDataQuery}`)
        .then(res => res.json()).then(data => {
            if (data.error) throw new Error(data.error);
            const score = data.score || 50;
            const aiHtml = data.sentiment ? `<div class="ai-verdict ${data.sentiment==='GO'?'ai-go':'ai-block'}">${data.sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${data.sentiment}</div>` : "";
            signalOutput.innerHTML = `
                <div style="font-weight:bold; margin-bottom:10px; border-bottom: 1px solid #444; padding-bottom:5px;">${data.pair} (${currentExpiration})</div>
                <div class="price-display-manual"><div style="color:#aaa;font-size:0.9em">Ціна входу</div><div class="signal-price">${data.price ? data.price.toFixed(5) : 'N/A'}</div></div>
                <div class="verdict">${data.verdict_text}</div>
                ${aiHtml}
                <div class="power-balance"><span>🐂 Бики: ${score}%</span><span>🐃 Ведмеді: ${100-score}%</span></div>
            `;
            // ПОВЕРНУТО: АВТОМАТИЧНИЙ СКРОЛЛ
            setTimeout(() => {
                const rect = signalOutput.getBoundingClientRect();
                window.scrollTo({ top: window.scrollY + rect.top - 20, behavior: 'smooth' });
            }, 100);
        }).catch(err => { signalOutput.innerHTML = `❌ Помилка: ${err.message}`; })
        .finally(() => showLoader(false));
}
function showLoader(v) { loader.className = v ? '' : 'hidden'; }