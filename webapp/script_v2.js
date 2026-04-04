const API_BASE_URL = window.API_BASE_URL || "";
const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
let currentWatchlist = [], allData = {}, currentExpiration = '1m', initData = window.Telegram?.WebApp?.initData || '';

document.addEventListener('DOMContentLoaded', () => {
    showLoader(true);
    const q = initData ? `?initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/get_pairs${q}`).then(res => res.json()).then(data => {
        allData = data;
        currentWatchlist = (data.watchlist || []).map(p => p.replace(/\//g, ''));
        populateLists(data);
        showLoader(false);
    }).catch(() => showLoader(false));

    const es = new EventSource(`${API_BASE_URL}/api/signal-stream${q}`);
    es.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.pair && d.price) {
            const el = document.getElementById(`price-${d.pair.replace(/\//g, "")}`);
            if (el) el.textContent = d.price.toFixed(5);
        }
    };
});

function populateLists(data) {
    let html = '';
    const createSection = (title, pairs) => {
        if (!pairs || !pairs.length) return '';
        let s = `<div class="category-title" style="color:#888; font-size:14px; margin:15px 10px 5px;">${title}</div><div class="pair-list" style="display:flex; flex-direction:column; gap:8px; padding:0 10px;">`;
        pairs.forEach(p => {
            const pId = p.replace(/\//g, "");
            s += `<div class="pair-item" style="display:flex; height:48px;">
                <button class="pair-button" onclick="fetchSignal('${p}')" style="flex-grow:1; display:flex; justify-content:space-between; align-items:center; padding:0 15px; background:#272727; border:none; color:white; border-radius:10px 0 0 10px; cursor:pointer;">
                    <span>${p}</span><span class="live-price-min" id="price-${pId}" style="font-family:monospace; color:#3390ec; background:rgba(0,0,0,0.3); padding:4px 8px; border-radius:5px;">---</span>
                </button>
                <button class="fav-btn" style="width:48px; background:#272727; border:none; color:white; border-radius:0 10px 10px 0; border-left:1px solid #1a1a1a;">${currentWatchlist.includes(pId) ? '✅' : '⭐'}</button>
            </div>`;
        });
        return s + '</div>';
    };
    if (currentWatchlist.length) html += createSection('⭐ Обране', currentWatchlist);
    if (data.forex) data.forex.forEach(session => html += createSection(session.title, session.pairs));
    html += createSection('💎 Криптовалюти', data.crypto);
    html += createSection('🥇 Сировина', data.commodities);
    html += createSection('📈 Акції/Індекси', data.stocks);
    listsContainer.innerHTML = html;
}

function fetchSignal(pair) {
    showLoader(true);
    signalOutput.innerHTML = `⏳ Аналіз ${pair}...`;
    const q = initData ? `&initData=${encodeURIComponent(initData)}` : '';
    fetch(`${API_BASE_URL}/api/signal?pair=${pair}&timeframe=${currentExpiration}${q}`).then(res => res.json()).then(d => {
        const score = d.score || 50;
        const ai = d.sentiment ? `<div class="ai-verdict ${d.sentiment==='GO'?'ai-go':'ai-block'}" style="padding:12px; border-radius:8px; text-align:center; font-weight:bold; margin:10px 0; border:1px solid">${d.sentiment==='GO'?'✅':'🚨'} ШІ Новини: ${d.sentiment}</div>` : "";
        signalOutput.innerHTML = `
            <div style="font-weight:bold; border-bottom:1px solid #444; padding-bottom:5px;">${d.pair}</div>
            <div style="text-align:center; padding:20px; background:#111; border-radius:12px; margin:15px 0; border:1px solid #333;">
                <div style="color:#aaa; font-size:12px; margin-bottom:5px;">Ціна входу</div>
                <div style="font-size:2.2em; font-family:monospace; font-weight:bold;">${d.price?d.price.toFixed(5):'N/A'}</div>
            </div>
            <div style="text-align:center; font-weight:bold; padding:12px; background:#222; border-radius:8px; border:1px solid #444;">${d.verdict_text}</div>
            ${ai}
            <div style="display:flex; justify-content:space-around; margin-top:15px; background:#111; padding:10px; border-radius:8px;"><span>🐂 Бики: ${score}%</span><span>🐃 Ведмеді: ${100-score}%</span></div>`;
        
        // АВТОСКРОЛ
        setTimeout(() => { signalOutput.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 150);
    }).finally(() => showLoader(false));
}
function showLoader(v) { loader.className = v ? '' : 'hidden'; }