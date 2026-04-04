const API_BASE_URL = window.API_BASE_URL || "";
const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
let currentWatchlist = [], allData = {}, lastSelectedPair = null, currentExpiration = '1m';
let initData = window.Telegram?.WebApp?.initData || '';

document.addEventListener('DOMContentLoaded', () => {
    showLoader(true);
    fetch(`${API_BASE_URL}/api/get_pairs${initData ? '?initData='+encodeURIComponent(initData) : ''}`)
        .then(res => res.json()).then(data => {
            allData = data;
            currentWatchlist = (data.watchlist || []).map(p => p.replace(/\//g, ''));
            populateLists(data);
            showLoader(false);
        }).catch(() => showLoader(false));

    const eventSource = new EventSource(`${API_BASE_URL}/api/signal-stream${initData ? '?initData='+encodeURIComponent(initData) : ''}`);
    eventSource.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.pair && data.price) {
            const pId = data.pair.replace(/\//g, "");
            const el = document.getElementById(`price-${pId}`);
            if (el) el.textContent = data.price.toFixed(5);
        }
    };
});

function populateLists(data) {
    let html = '';
    const sections = [
        { t: "⭐ Обране", d: currentWatchlist },
        { t: "💎 Криптовалюти", d: data.crypto },
        { t: "🥇 Сировина", d: data.commodities },
        { t: "📈 Акції/Індекси", d: data.stocks }
    ];
    sections.forEach(s => {
        if (!s.d || s.d.length === 0) return;
        html += `<div class="category-title">${s.t}</div><div class="pair-list">`;
        s.d.forEach(p => {
            const pId = p.replace(/\//g, "");
            html += `<div class="pair-item">
                <button class="pair-button" onclick="fetchSignal('${p}')">
                    <span>${p}</span><span class="live-price-min" id="price-${pId}">---</span>
                </button>
                <button class="fav-btn">${currentWatchlist.includes(pId) ? '✅' : '⭐'}</button>
            </div>`;
        });
        html += `</div>`;
    });
    listsContainer.innerHTML = html;
}

function fetchSignal(pair) {
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${initData ? '&initData='+encodeURIComponent(initData) : ''}`)
        .then(res => res.json()).then(data => {
            if (data.error) throw new Error(data.error);
            const score = data.score || 50;
            const aiHtml = data.sentiment ? `<div class="ai-verdict ${data.sentiment==='GO'?'ai-go':'ai-block'}">${data.sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${data.sentiment}</div>` : "";
            signalOutput.innerHTML = `
                <div style="font-weight:bold; margin-bottom:10px;">${data.pair} (${currentExpiration})</div>
                <div class="price-display-manual"><div style="color:#aaa;font-size:0.9em">Ціна входу</div><div class="signal-price">${data.price ? data.price.toFixed(5) : 'N/A'}</div></div>
                <div class="verdict">${data.verdict_text}</div>
                ${aiHtml}
                <div class="power-balance"><span>🐂 Бики: ${score}%</span><span>🐃 Ведмеді: ${100-score}%</span></div>
            `;
        }).catch(err => { signalOutput.innerHTML = `❌ Помилка: ${err.message}`; })
        .finally(() => showLoader(false));
}
function showLoader(v) { loader.className = v ? '' : 'hidden'; }