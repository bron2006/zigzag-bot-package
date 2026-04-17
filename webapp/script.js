const API_BASE_URL = window.API_BASE_URL || "";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const scannerControls = document.getElementById("scannerControls");
const liveSignalsContainer = document.getElementById("liveSignalsContainer");
const signalContainer = document.getElementById("signalContainer");

let tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

let currentWatchlist = [];
let initData = tg.initData || "";
let currentExpiration = "1m";
let allData = {};
let lastSelectedPair = null;
let currentSignalData = null;
let latestPrices = {};

let signalEventSource = null;
let priceEventSource = null;

const debouncedFetchSignal = debounce(fetchSignal, 300);

document.addEventListener("DOMContentLoaded", function () {
    showLoader(true);

    loadInitialData();
    bindScannerControls();
    bindTimeframeButtons();
    bindSearch();
    connectSignalStream();
    connectPriceStream();
});

function buildQuery(params = {}) {
    const search = new URLSearchParams();

    if (initData) {
        search.set("initData", initData);
    }

    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
            search.set(key, String(value));
        }
    });

    const qs = search.toString();
    return qs ? `?${qs}` : "";
}

async function apiGet(path, params = {}) {
    const url = `${API_BASE_URL}${path}${buildQuery(params)}`;
    const response = await fetch(url);

    if (!response.ok) {
        throw new Error(`HTTP ${response.status} for ${path}`);
    }

    return response.json();
}

async function loadInitialData() {
    try {
        const staticData = await apiGet("/api/get_pairs");
        allData = staticData || {};
        currentWatchlist = ((staticData && staticData.watchlist) || []).map(normalizePair);

        populateLists(allData);
        showLoader(false);
    } catch (err) {
        console.error("Pairs load error:", err);
        showLoader(false);
    }

    try {
        const state = await apiGet("/api/scanner/status");
        updateScannerButtons(state);
    } catch (err) {
        console.warn("Scanner status unavailable:", err);
        updateScannerButtons({
            forex: false,
            crypto: false,
            commodities: false,
            watchlist: false,
        });
    }
}

function bindScannerControls() {
    if (!scannerControls) return;

    scannerControls.addEventListener("click", async (event) => {
        const button = event.target.closest(".scanner-button");
        if (!button) return;

        const category = button.dataset.cat;
        if (!category) return;

        try {
            const url = `${API_BASE_URL}/api/scanner/toggle${buildQuery({ category })}`;
            const response = await fetch(url, { method: "GET" });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const newState = await response.json();
            updateScannerButtons(newState);
        } catch (err) {
            console.error("Scanner toggle error:", err);
        }
    });
}

function bindTimeframeButtons() {
    const expirationButtons = document.querySelectorAll(".tf-button");
    expirationButtons.forEach((button) => {
        button.addEventListener("click", () => {
            expirationButtons.forEach((btn) => btn.classList.remove("active"));
            button.classList.add("active");
            currentExpiration = button.dataset.exp;

            if (lastSelectedPair) {
                fetchSignal(lastSelectedPair);
            }
        });
    });
}

function bindSearch() {
    const searchInput = document.getElementById("searchInput");
    if (!searchInput) return;

    searchInput.addEventListener(
        "input",
        debounce((e) => populateLists(allData, e.target.value), 300)
    );
}

function connectSignalStream() {
    try {
        const url = `${API_BASE_URL}/api/signal-stream${buildQuery()}`;
        signalEventSource = new EventSource(url);

        signalEventSource.onmessage = function (event) {
            try {
                const data = JSON.parse(event.data);

                if (!data || data._ping) return;
                if (data.type && data.type !== "signal") return;
                if (!isSignalPayload(data)) return;

                displayLiveSignal(data);
            } catch (err) {
                console.error("Signal stream parse error:", err, event.data);
            }
        };

        signalEventSource.onerror = function (err) {
            console.warn("Signal stream error:", err);
        };
    } catch (err) {
        console.error("Failed to connect signal stream:", err);
    }
}

function connectPriceStream() {
    try {
        const url = `${API_BASE_URL}/api/price-stream${buildQuery()}`;
        priceEventSource = new EventSource(url);

        priceEventSource.onmessage = function (event) {
            try {
                const data = JSON.parse(event.data);

                if (!data || data._ping) return;
                if (data.type !== "price") return;
                if (!isPricePayload(data)) return;

                const pairNorm = normalizePair(data.pair);
                latestPrices[pairNorm] = data;

                updatePairPriceInList(pairNorm, data);
                updateOpenSignalPrice(pairNorm, data);
            } catch (err) {
                console.error("Price stream parse error:", err, event.data);
            }
        };

        priceEventSource.onerror = function (err) {
            console.warn("Price stream error:", err);
        };
    } catch (err) {
        console.error("Failed to connect price stream:", err);
    }
}

function normalizePair(pair) {
    return String(pair || "").replace(/\//g, "").toUpperCase();
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function labelVerdict(value) {
    const labels = {
        BUY: "купівля",
        SELL: "продаж",
        NEUTRAL: "нейтрально",
        WAIT: "очікування",
        NEWS_WAIT: "пауза через новини",
        ERROR: "помилка",
    };

    return labels[String(value || "").toUpperCase()] || "невідомо";
}

function labelSentiment(value) {
    const labels = {
        GO: "дозволено",
        BLOCK: "заблоковано",
    };

    return labels[String(value || "").toUpperCase()] || "невідомо";
}

function labelTimeframe(value) {
    const labels = {
        "1m": "1 хв",
        "5m": "5 хв",
        "15m": "15 хв",
    };

    return labels[String(value || "")] || String(value || "");
}

function localizeReason(reason) {
    let text = String(reason || "");
    const replacements = [
        ["NEWS_WAIT", "пауза через новини"],
        ["NEUTRAL", "нейтрально"],
        ["BLOCK", "заблоковано"],
        ["BUY", "купівля"],
        ["SELL", "продаж"],
        ["WAIT", "очікування"],
        ["ERROR", "помилка"],
        ["GO", "дозволено"],
        ["TF:", "Таймфрейми:"],
        ["News filter:", "Фільтр новин:"],
        ["ML", "ШІ"],
        ["fallback", "резервний режим"],
        ["timeout", "час очікування вичерпано"],
        ["invalid_json_response", "некоректна відповідь"],
        ["all_models_unavailable", "моделі недоступні"],
        ["Symbol not found", "символ не знайдено"],
        ["No Account ID", "акаунт не готовий"],
        ["Unsupported timeframe", "непідтримуваний таймфрейм"],
        ["No trendbars returned", "історичні дані не отримано"],
        ["1m", "1 хв"],
        ["5m", "5 хв"],
        ["15m", "15 хв"],
    ];

    replacements.forEach(([source, target]) => {
        text = text.split(source).join(target);
    });

    return text;
}

function isSignalPayload(data) {
    return (
        data &&
        typeof data === "object" &&
        typeof data.pair !== "undefined" &&
        typeof data.verdict_text !== "undefined" &&
        typeof data.score !== "undefined"
    );
}

function isPricePayload(data) {
    return (
        data &&
        typeof data === "object" &&
        typeof data.pair !== "undefined" &&
        (
            typeof data.mid === "number" ||
            typeof data.bid === "number" ||
            typeof data.ask === "number"
        )
    );
}

function updateScannerButtons(stateDict) {
    if (!stateDict || !scannerControls) return;

    const textMap = {
        forex: "Forex",
        crypto: "Crypto",
        commodities: "Сировина",
        watchlist: "Обране",
    };

    Object.keys(textMap).forEach((cat) => {
        const btn = scannerControls.querySelector(`.scanner-button[data-cat="${cat}"]`);
        if (!btn) return;

        const isEnabled = stateDict[cat] === true;
        btn.textContent = `${isEnabled ? "✅" : "❌"} ${textMap[cat]}`;
        btn.classList.toggle("enabled", isEnabled);
    });
}

function displayLiveSignal(signalData) {
    if (!liveSignalsContainer) return;

    const pairNorm = normalizePair(signalData.pair);
    const existing = liveSignalsContainer.querySelector(`.live-signal[data-pair="${pairNorm}"]`);

    const typeClass =
        signalData.verdict_text === "BUY"
            ? "buy"
            : signalData.verdict_text === "SELL"
                ? "sell"
                : "neutral";

    const html = `
        <div class="live-signal-content" style="text-align:center; font-size:13px;">
            <strong>${escapeHtml(signalData.pair)}</strong>: ${escapeHtml(labelVerdict(signalData.verdict_text))} (${Number(signalData.score) || 0}%)
        </div>
        <div class="live-signal-timer"></div>
    `;

    let signalDiv = existing;
    if (!signalDiv) {
        signalDiv = document.createElement("div");
        signalDiv.className = "live-signal";
        signalDiv.dataset.pair = pairNorm;
        liveSignalsContainer.prepend(signalDiv);
    }

    signalDiv.className = "live-signal";
    signalDiv.classList.add(typeClass);
    signalDiv.innerHTML = html;

    signalDiv.onclick = () => {
        currentSignalData = { ...signalData };
        signalOutput.innerHTML = formatSignalAsHtml(currentSignalData, currentExpiration);
        signalContainer.scrollIntoView({ behavior: "smooth" });
        signalDiv.remove();
    };

    clearTimeout(signalDiv._removeTimer);
    signalDiv._removeTimer = setTimeout(() => {
        if (signalDiv.parentElement) {
            signalDiv.remove();
        }
    }, 15000);
}

function populateLists(data, query = "") {
    if (!listsContainer) return;

    let html = "";
    const queryLower = String(query || "").toLowerCase();

    function createSection(title, pairs) {
        if (!Array.isArray(pairs)) return "";

        const filteredPairs = pairs.filter((p) => String(p).toLowerCase().includes(queryLower));
        if (filteredPairs.length === 0) return "";

        let sectionHtml = `<div class="category"><div class="category-title">${escapeHtml(title)}</div><div class="pair-list">`;

        filteredPairs.forEach((pair) => {
            const pairNorm = normalizePair(pair);
            const isFav = currentWatchlist.includes(pairNorm);
            const price = latestPrices[pairNorm];
            const priceText =
                price && typeof price.mid === "number"
                    ? price.mid.toFixed(5)
                    : "—";

            sectionHtml += `
                <div class="pair-item">
                    <button class="pair-button" data-pair="${escapeHtml(pair)}">
                        <span>${escapeHtml(pair)}</span>
                        <span class="pair-price" id="price-${pairNorm}" data-pair="${pairNorm}">${priceText}</span>
                    </button>
                    <button class="fav-btn" onclick="toggleFavorite(event, this, '${escapeJsString(pair)}')">
                        ${isFav ? "✅" : "⭐"}
                    </button>
                </div>
            `;
        });

        return sectionHtml + "</div></div>";
    }

    const allPairs = [
        ...(data.forex ? data.forex.map((s) => s.pairs).flat() : []),
        ...(data.crypto || []),
        ...(data.stocks || []),
        ...(data.commodities || []),
    ];

    if (currentWatchlist.length > 0) {
        const wl = currentWatchlist.map(
            (pairNorm) => allPairs.find((p) => normalizePair(p) === pairNorm) || pairNorm
        );
        html += createSection("⭐ Обране", wl);
    }

    if (data.forex) {
        data.forex.forEach((session) => {
            html += createSection(session.title, session.pairs);
        });
    }

    if (data.crypto) html += createSection("💎 Криптовалюти", data.crypto);
    if (data.commodities) html += createSection("🥇 Сировина", data.commodities);
    if (data.stocks) html += createSection("📈 Акції/Індекси", data.stocks);

    listsContainer.innerHTML = html;

    listsContainer.querySelectorAll(".pair-button").forEach((btn) => {
        btn.addEventListener("click", (e) => debouncedFetchSignal(e.currentTarget.dataset.pair));
    });
}

function updatePairPriceInList(pairNorm, priceData) {
    const priceNode = document.getElementById(`price-${pairNorm}`);
    if (!priceNode) return;

    let priceText = "—";
    if (typeof priceData.mid === "number") {
        priceText = priceData.mid.toFixed(5);
    } else if (typeof priceData.bid === "number") {
        priceText = priceData.bid.toFixed(5);
    } else if (typeof priceData.ask === "number") {
        priceText = priceData.ask.toFixed(5);
    }

    if (priceNode.textContent !== priceText) {
        priceNode.textContent = priceText;
    }
}

function updateOpenSignalPrice(pairNorm, priceData) {
    if (!currentSignalData || !lastSelectedPair) return;

    const selectedNorm = normalizePair(lastSelectedPair);
    if (selectedNorm !== pairNorm) return;

    const nextPrice =
        typeof priceData.mid === "number"
            ? priceData.mid
            : typeof priceData.bid === "number"
                ? priceData.bid
                : typeof priceData.ask === "number"
                    ? priceData.ask
                    : null;

    if (typeof nextPrice !== "number") return;

    currentSignalData = {
        ...currentSignalData,
        price: nextPrice,
    };

    signalOutput.innerHTML = formatSignalAsHtml(currentSignalData, currentExpiration);
}

async function toggleFavorite(event, button, pair) {
    event.stopPropagation();

    const pairNorm = normalizePair(pair);

    try {
        const url = `${API_BASE_URL}/api/toggle_watchlist${buildQuery({ pair })}`;
        const response = await fetch(url, { method: "GET" });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const res = await response.json();

        if (res.success) {
            if (currentWatchlist.includes(pairNorm)) {
                currentWatchlist = currentWatchlist.filter((p) => p !== pairNorm);
            } else {
                currentWatchlist.push(pairNorm);
            }

            try {
                const refreshed = await apiGet("/api/get_pairs");
                allData = refreshed || allData;
                currentWatchlist = ((refreshed && refreshed.watchlist) || []).map(normalizePair);
            } catch (refreshErr) {
                console.warn("Watchlist refresh failed, using local state:", refreshErr);
            }

            const searchInput = document.getElementById("searchInput");
            populateLists(allData, searchInput ? searchInput.value : "");
        }
    } catch (err) {
        console.error("Toggle favorite error:", err);
    }
}

async function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `<div style="text-align:center; padding:10px;">⏳ Аналіз ${escapeHtml(pair)}...</div>`;

    try {
        const url = `${API_BASE_URL}/api/signal${buildQuery({
            pair,
            timeframe: currentExpiration,
        })}`;

        const res = await fetch(url);
        const data = await res.json();

        currentSignalData = data;
        signalOutput.innerHTML = formatSignalAsHtml(data, currentExpiration);

        setTimeout(() => {
            signalContainer.scrollIntoView({ behavior: "smooth" });
        }, 80);
    } catch (err) {
        console.error("Fetch signal error:", err);
        currentSignalData = null;
        signalOutput.innerHTML = `
            <div style="text-align:center; color:#ef5350; padding:10px;">
                ❌ Помилка запиту до сервера
            </div>
        `;
    } finally {
        showLoader(false);
    }
}

function renderTimeframeDetails(signalData) {
    const details = signalData?.timeframe_details || {};
    const entries = Object.entries(details);
    if (!entries.length) return "";

    const rows = entries.map(([tf, item]) => {
        const rawVerdict = item?.verdict || "немає даних";
        const verdict = escapeHtml(labelVerdict(rawVerdict));
        const score = Number.isFinite(Number(item?.score)) ? Number(item.score) : 50;

        let color = "#94a3b8";
        if (rawVerdict === "BUY") color = "#26a69a";
        else if (rawVerdict === "SELL") color = "#ef5350";

        return `
            <div style="flex:1; min-width:92px; padding:6px 8px; border:1px solid rgba(255,255,255,0.08); border-radius:8px; background:rgba(255,255,255,0.02);">
                <div style="font-size:10px; color:#94a3b8; margin-bottom:2px;">${escapeHtml(labelTimeframe(tf))}</div>
                <div style="font-size:15px; font-weight:800; color:${color}; line-height:1.05;">${verdict}</div>
                <div style="font-size:13px; color:#fff; line-height:1.05;">${score}%</div>
            </div>
        `;
    }).join("");

    return `
        <div style="display:flex; gap:8px; flex-wrap:wrap; margin:8px 0 6px;">
            ${rows}
        </div>
    `;
}

function formatSignalAsHtml(signalData, exp) {
    if (!signalData || signalData.error) {
        return `
            <div style="text-align:center; color:#ef5350; padding:10px;">
                ❌ Помилка: технічна помилка аналізу
            </div>
        `;
    }

    const pair = escapeHtml(signalData.pair || "немає даних");
    const price = signalData.price;
    const verdictText = escapeHtml(labelVerdict(signalData.verdict_text || "WAIT"));
    const score = Number.isFinite(Number(signalData.score)) ? Number(signalData.score) : 50;
    const rawSentiment = signalData.sentiment || "";
    const sentiment = rawSentiment ? escapeHtml(labelSentiment(rawSentiment)) : "";
    const reasons = Array.isArray(signalData.reasons) ? signalData.reasons : [];
    const tradeAllowed = Boolean(signalData.is_trade_allowed);

    let arrow = "↔️";
    let cClass = "neutral";

    if (signalData.verdict_text === "BUY") {
        arrow = "⬆️";
        cClass = "buy";
    } else if (signalData.verdict_text === "SELL") {
        arrow = "⬇️";
        cClass = "sell";
    } else if (signalData.verdict_text === "NEWS_WAIT") {
        arrow = "⏸️";
        cClass = "neutral";
    }

    const safePrice =
        typeof price === "number"
            ? price.toFixed(5)
            : "немає даних";

    return `
        <div class="signal-header" style="text-align:center; font-size:1em; margin-bottom:6px;">
            <strong>${pair}</strong> <span style="color:#64748b; font-size:0.74em;">(Експірація: ${escapeHtml(labelTimeframe(exp))})</span>
        </div>
        <div class="verdict-container" style="text-align:center; margin:6px 0 10px;">
            <div class="arrow" style="font-size:48px; line-height:0.95; display:block; margin-bottom:2px;">${arrow}</div>
            <div class="v-text ${cClass}" style="font-size:23px; font-weight:900; display:block; line-height:1;">${verdictText}</div>
            <div style="font-size:16px; color:#3390ec; font-family:monospace; margin-top:3px; display:block; line-height:1;">${safePrice}</div>
        </div>
        ${
            sentiment
                ? `<div class="ai-verdict" style="padding:5px 9px; border-radius:8px; text-align:center; font-weight:bold; margin:5px auto; border:1px solid; background:rgba(0,0,0,0.1); color:${rawSentiment === "GO" ? "#26a69a" : "#ef5350"}; width:fit-content; font-size:12px;">
                    ${rawSentiment === "GO" ? "✅" : "🚨"} ШІ: ${sentiment}
                   </div>`
                : ""
        }
        <div class="power-balance" style="display:flex; justify-content:space-around; margin:7px 0; font-weight:bold; text-align:center; font-size:13px;">
            <span style="color:#26a69a;">🐂 ${score}%</span>
            <span style="color:#ef5350;">🐃 ${100 - score}%</span>
        </div>
        ${renderTimeframeDetails(signalData)}
        <div style="text-align:center; margin-top:5px; font-weight:bold; color:${tradeAllowed ? "#26a69a" : "#ef5350"}; font-size:13px;">
            ${tradeAllowed ? "✅ Вхід дозволено" : "⛔ Вхід не рекомендований"}
        </div>
        ${
            reasons.length
                ? `<div class="reasons" style="text-align:left; margin-top:9px; border-top:1px solid rgba(255,255,255,0.1); padding-top:7px; font-size:12px; line-height:1.2;">
                    ${reasons.map((r) => `<div style="margin-bottom:4px;">• ${escapeHtml(localizeReason(r))}</div>`).join("")}
                   </div>`
                : ""
        }
    `;
}

function showLoader(visible) {
    if (!loader) return;
    loader.className = visible ? "" : "hidden";
}

function debounce(func, delay) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), delay);
    };
}

function escapeJsString(value) {
    return String(value ?? "")
        .replace(/\\/g, "\\\\")
        .replace(/'/g, "\\'");
}
