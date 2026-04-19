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
let brokerSymbolsLoaded = false;
let unavailablePairs = new Set();

let signalEventSource = null;
let priceEventSource = null;

const debouncedFetchSignal = debounce(fetchSignal, 300);
const WATCHLIST_STORAGE_KEY = "zigzag_watchlist";
const LANG_STORAGE_KEY = "zigzag_language";
const TIMEZONE_STORAGE_KEY = "zigzag_timezone";
let userTimezone = normalizeTimezone(
    localStorage.getItem(TIMEZONE_STORAGE_KEY)
    || Intl.DateTimeFormat().resolvedOptions().timeZone
);
let userLang = normalizeAppLanguage(
    localStorage.getItem(LANG_STORAGE_KEY) || tg.initDataUnsafe?.user?.language_code
);
let scannerState = null;

const APP_I18N = {
    en: {
        languageLabel: "Language",
        appTitle: "Terminal | Binary Options",
        search: "🔍 Search...",
        expiration1m: "Expiration 1 min",
        expiration5m: "Expiration 5 min",
        chooseAsset: "Choose an asset for analysis...",
        forex: "Currencies",
        crypto: "Crypto",
        commodities: "Commodities",
        watchlist: "Favorites",
        stocks: "Stocks/Indices",
        noBroker: "not at broker",
        noBrokerTitle: "This symbol is not in the broker list",
        noData: "no data",
        analyzing: "Analyzing {pair}...",
        requestFailed: "❌ Server request failed",
        analysisError: "technical analysis error",
        expiration: "Expiration",
        news: "News",
        bulls: "Bulls",
        bears: "Bears",
        sourceCheck: "Source check",
        price: "Price",
        calendar: "Calendar",
        model: "Model",
        marketData: "Historical data",
        signalQuality: "Signal quality",
        entryAllowed: "✅ Entry allowed",
        entryNotRecommended: "⛔ Entry not recommended",
        favoriteNotUpdated: "Favorites were not updated",
        favoriteSavedLocal: "Favorites were saved on this device. The server did not respond.",
    },
    uk: {
        languageLabel: "Мова",
        appTitle: "Термінал | Бінарні Опціони",
        search: "🔍 Пошук...",
        expiration1m: "Експірація 1 хв",
        expiration5m: "Експірація 5 хв",
        chooseAsset: "Оберіть актив для аналізу...",
        forex: "Валюти",
        crypto: "Криптовалюти",
        commodities: "Сировина",
        watchlist: "Обране",
        stocks: "Акції/Індекси",
        noBroker: "немає у брокера",
        noBrokerTitle: "Цього символу немає в списку брокера",
        noData: "немає даних",
        analyzing: "Аналіз {pair}...",
        requestFailed: "❌ Помилка запиту до сервера",
        analysisError: "технічна помилка аналізу",
        expiration: "Експірація",
        news: "Новини",
        bulls: "Бики",
        bears: "Ведмеді",
        sourceCheck: "Перевірка джерел",
        price: "Ціна",
        calendar: "Календар",
        model: "Модель",
        marketData: "Історичні дані",
        signalQuality: "Якість сигналу",
        entryAllowed: "✅ Вхід дозволено",
        entryNotRecommended: "⛔ Вхід не рекомендований",
        favoriteNotUpdated: "Обране не оновлено",
        favoriteSavedLocal: "Обране збережено на цьому пристрої. Сервер тимчасово не відповів.",
    },
    es: {
        languageLabel: "Idioma",
        appTitle: "Terminal | Opciones Binarias",
        search: "🔍 Buscar...",
        expiration1m: "Expiración 1 min",
        expiration5m: "Expiración 5 min",
        chooseAsset: "Elige un activo para analizar...",
        forex: "Divisas",
        crypto: "Cripto",
        commodities: "Materias primas",
        watchlist: "Favoritos",
        stocks: "Acciones/Índices",
        noBroker: "no está en el broker",
        noBrokerTitle: "Este símbolo no está en la lista del broker",
        noData: "sin datos",
        analyzing: "Analizando {pair}...",
        requestFailed: "❌ Error de solicitud al servidor",
        analysisError: "error técnico de análisis",
        expiration: "Expiración",
        news: "Noticias",
        bulls: "Toros",
        bears: "Osos",
        sourceCheck: "Verificación de fuentes",
        price: "Precio",
        calendar: "Calendario",
        model: "Modelo",
        marketData: "Datos históricos",
        signalQuality: "Calidad de señal",
        entryAllowed: "✅ Entrada permitida",
        entryNotRecommended: "⛔ Entrada no recomendada",
        favoriteNotUpdated: "Favoritos no actualizados",
        favoriteSavedLocal: "Favoritos guardados en este dispositivo. El servidor no respondió.",
    },
    de: {
        languageLabel: "Sprache",
        appTitle: "Terminal | Binäre Optionen",
        search: "🔍 Suche...",
        expiration1m: "Expiration 1 Min",
        expiration5m: "Expiration 5 Min",
        chooseAsset: "Asset für Analyse wählen...",
        forex: "Währungen",
        crypto: "Krypto",
        commodities: "Rohstoffe",
        watchlist: "Favoriten",
        stocks: "Aktien/Indizes",
        noBroker: "nicht beim Broker",
        noBrokerTitle: "Dieses Symbol ist nicht in der Brokerliste",
        noData: "keine Daten",
        analyzing: "Analysiere {pair}...",
        requestFailed: "❌ Serveranfrage fehlgeschlagen",
        analysisError: "technischer Analysefehler",
        expiration: "Expiration",
        news: "Nachrichten",
        bulls: "Bullen",
        bears: "Bären",
        sourceCheck: "Quellenprüfung",
        price: "Preis",
        calendar: "Kalender",
        model: "Modell",
        marketData: "Historische Daten",
        signalQuality: "Signalqualität",
        entryAllowed: "✅ Einstieg erlaubt",
        entryNotRecommended: "⛔ Einstieg nicht empfohlen",
        favoriteNotUpdated: "Favoriten wurden nicht aktualisiert",
        favoriteSavedLocal: "Favoriten wurden auf diesem Gerät gespeichert. Der Server antwortete nicht.",
    },
    ru: {
        languageLabel: "Язык",
        appTitle: "Терминал | Бинарные Опционы",
        search: "🔍 Поиск...",
        expiration1m: "Экспирация 1 мин",
        expiration5m: "Экспирация 5 мин",
        chooseAsset: "Выберите актив для анализа...",
        forex: "Валюты",
        crypto: "Криптовалюты",
        commodities: "Сырье",
        watchlist: "Избранное",
        stocks: "Акции/Индексы",
        noBroker: "нет у брокера",
        noBrokerTitle: "Этого символа нет в списке брокера",
        noData: "нет данных",
        analyzing: "Анализ {pair}...",
        requestFailed: "❌ Ошибка запроса к серверу",
        analysisError: "техническая ошибка анализа",
        expiration: "Экспирация",
        news: "Новости",
        bulls: "Быки",
        bears: "Медведи",
        sourceCheck: "Проверка источников",
        price: "Цена",
        calendar: "Календарь",
        model: "Модель",
        marketData: "Исторические данные",
        signalQuality: "Качество сигнала",
        entryAllowed: "✅ Вход разрешен",
        entryNotRecommended: "⛔ Вход не рекомендован",
        favoriteNotUpdated: "Избранное не обновлено",
        favoriteSavedLocal: "Избранное сохранено на этом устройстве. Сервер не ответил.",
    },
};

document.addEventListener("DOMContentLoaded", function () {
    applyStaticTranslations();
    showLoader(true);

    loadInitialData();
    bindScannerControls();
    bindLanguageSelector();
    bindTimeframeButtons();
    bindSearch();
    connectSignalStream();
    connectPriceStream();
});

function buildQuery(params = {}) {
    const search = new URLSearchParams();

    search.set("lang", userLang);
    search.set("timezone", userTimezone);

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

function normalizeAppLanguage(lang) {
    const base = String(lang || "").split(/[-_]/)[0].toLowerCase();
    return ["uk", "en", "es", "de", "ru"].includes(base) ? base : "en";
}

function normalizeTimezone(value) {
    const timezone = String(value || "").trim();
    if (!timezone) return "Europe/Kyiv";

    try {
        Intl.DateTimeFormat("en-US", { timeZone: timezone }).format(new Date());
        return timezone;
    } catch (err) {
        return "Europe/Kyiv";
    }
}

function setUserTimezone(timezone) {
    userTimezone = normalizeTimezone(timezone);
    localStorage.setItem(TIMEZONE_STORAGE_KEY, userTimezone);
    return userTimezone;
}

function tr(key, params = {}) {
    let text = (APP_I18N[userLang] && APP_I18N[userLang][key]) || APP_I18N.en[key] || key;
    Object.entries(params).forEach(([name, value]) => {
        text = text.split(`{${name}}`).join(String(value));
    });
    return text;
}

function applyStaticTranslations() {
    document.documentElement.lang = userLang;
    document.title = userLang === "uk" ? "ZigZag | Бінарні опціони" : "ZigZag | Binary Options";

    const title = document.getElementById("appTitle");
    if (title) title.textContent = tr("appTitle");

    const searchInput = document.getElementById("searchInput");
    if (searchInput) searchInput.placeholder = tr("search");

    const tf1 = document.querySelector('.tf-button[data-exp="1m"]');
    const tf5 = document.querySelector('.tf-button[data-exp="5m"]');
    if (tf1) tf1.textContent = tr("expiration1m");
    if (tf5) tf5.textContent = tr("expiration5m");

    if (signalOutput) signalOutput.textContent = tr("chooseAsset");

    document.querySelectorAll(".lang-button").forEach((button) => {
        button.classList.toggle("active", button.dataset.lang === userLang);
    });
}

async function apiGet(path, params = {}) {
    const url = `${API_BASE_URL}${path}${buildQuery(params)}`;
    const response = await fetch(url);

    if (!response.ok) {
        throw new Error(`HTTP ${response.status} for ${path}`);
    }

    return response.json();
}

function applyPairMetadata(staticData) {
    brokerSymbolsLoaded = Boolean(staticData && staticData.symbols_loaded);
    unavailablePairs = new Set(((staticData && staticData.unavailable_pairs) || []).map(normalizePair));
}

function loadLocalWatchlist() {
    try {
        const raw = localStorage.getItem(WATCHLIST_STORAGE_KEY);
        const parsed = JSON.parse(raw || "[]");
        return Array.isArray(parsed) ? parsed.map(normalizePair).filter(Boolean) : [];
    } catch (err) {
        console.warn("Local watchlist load failed:", err);
        return [];
    }
}

function saveLocalWatchlist(items) {
    try {
        const unique = Array.from(new Set((items || []).map(normalizePair).filter(Boolean)));
        localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(unique));
    } catch (err) {
        console.warn("Local watchlist save failed:", err);
    }
}

function mergeWatchlists(remoteItems) {
    return Array.from(
        new Set([
            ...((remoteItems || []).map(normalizePair)),
            ...loadLocalWatchlist(),
        ].filter(Boolean))
    );
}

function configuredPairSet(data = allData) {
    const pairs = [
        ...(data && data.forex ? data.forex.map((s) => s.pairs).flat() : []),
        ...((data && data.crypto) || []),
        ...((data && data.stocks) || []),
        ...((data && data.commodities) || []),
    ];
    return new Set(pairs.map(normalizePair).filter(Boolean));
}

function setCurrentWatchlist(items) {
    const configured = configuredPairSet();
    currentWatchlist = Array.from(new Set((items || []).map(normalizePair).filter(Boolean)))
        .filter((pair) => configured.size === 0 || configured.has(pair));
    saveLocalWatchlist(currentWatchlist);
    if (allData) {
        allData.watchlist = currentWatchlist;
    }
}

async function loadInitialData() {
    try {
        const staticData = await apiGet("/api/get_pairs");
        if (staticData && staticData.language) {
            setUserLanguage(staticData.language, { persist: false, redraw: false });
        }
        if (staticData && staticData.timezone) {
            setUserTimezone(staticData.timezone);
        }
        allData = staticData || {};
        setCurrentWatchlist(mergeWatchlists((staticData && staticData.watchlist) || []));
        applyPairMetadata(staticData);

        populateLists(allData);
        showLoader(false);
    } catch (err) {
        console.error("Pairs load error:", err);
        showLoader(false);
    }

    try {
        const state = await apiGet("/api/scanner/status");
        scannerState = state;
        updateScannerButtons(state);
    } catch (err) {
        console.warn("Scanner status unavailable:", err);
        scannerState = {
            forex: false,
            crypto: false,
            commodities: false,
            watchlist: false,
        };
        updateScannerButtons(scannerState);
    }
}

function setUserLanguage(lang, options = {}) {
    const nextLang = normalizeAppLanguage(lang);
    const changed = nextLang !== userLang;
    userLang = nextLang;
    localStorage.setItem(LANG_STORAGE_KEY, userLang);
    applyStaticTranslations();

    if (options.redraw !== false) {
        updateScannerButtons(scannerState);
        populateLists(allData, document.getElementById("searchInput")?.value || "");
        if (currentSignalData) {
            signalOutput.innerHTML = formatSignalAsHtml(currentSignalData, currentExpiration);
        }
    }

    return changed;
}

function reconnectStreams() {
    if (signalEventSource) {
        signalEventSource.close();
        signalEventSource = null;
    }
    if (priceEventSource) {
        priceEventSource.close();
        priceEventSource = null;
    }
    connectSignalStream();
    connectPriceStream();
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
            scannerState = newState;
            updateScannerButtons(newState);
        } catch (err) {
            console.error("Scanner toggle error:", err);
        }
    });
}

function bindLanguageSelector() {
    const selector = document.getElementById("languageSelector");
    if (!selector) return;

    selector.addEventListener("click", async (event) => {
        const button = event.target.closest(".lang-button");
        if (!button || !button.dataset.lang) return;

        const nextLang = normalizeAppLanguage(button.dataset.lang);
        setUserLanguage(nextLang);

        try {
            const res = await apiGet("/api/language", { language: nextLang });
            if (res && res.language) {
                setUserLanguage(res.language);
            }
            if (res && res.timezone) {
                setUserTimezone(res.timezone);
            }
        } catch (err) {
            console.warn("Language save failed, using local preference:", err);
        }

        reconnectStreams();
        loadInitialData();
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
        en: {
            BUY: "buy",
            SELL: "sell",
            NEUTRAL: "neutral",
            WAIT: "wait",
            NEWS_WAIT: "news pause",
            ERROR: "error",
            UNKNOWN: "unknown",
        },
        uk: {
            BUY: "купівля",
            SELL: "продаж",
            NEUTRAL: "нейтрально",
            WAIT: "очікування",
            NEWS_WAIT: "пауза через новини",
            ERROR: "помилка",
            UNKNOWN: "невідомо",
        },
        es: {
            BUY: "compra",
            SELL: "venta",
            NEUTRAL: "neutral",
            WAIT: "esperar",
            NEWS_WAIT: "pausa por noticias",
            ERROR: "error",
            UNKNOWN: "desconocido",
        },
        de: {
            BUY: "kauf",
            SELL: "verkauf",
            NEUTRAL: "neutral",
            WAIT: "warten",
            NEWS_WAIT: "nachrichtenpause",
            ERROR: "fehler",
            UNKNOWN: "unbekannt",
        },
        ru: {
            BUY: "покупка",
            SELL: "продажа",
            NEUTRAL: "нейтрально",
            WAIT: "ожидание",
            NEWS_WAIT: "пауза из-за новостей",
            ERROR: "ошибка",
            UNKNOWN: "неизвестно",
        },
    };

    const dict = labels[userLang] || labels.en;
    return dict[String(value || "").toUpperCase()] || dict.UNKNOWN;
}

function labelSentiment(value) {
    const labels = {
        en: { GO: "allowed", BLOCK: "blocked", UNKNOWN: "unknown" },
        uk: { GO: "дозволено", BLOCK: "заблоковано", UNKNOWN: "невідомо" },
        es: { GO: "permitido", BLOCK: "bloqueado", UNKNOWN: "desconocido" },
        de: { GO: "erlaubt", BLOCK: "blockiert", UNKNOWN: "unbekannt" },
        ru: { GO: "разрешено", BLOCK: "заблокировано", UNKNOWN: "неизвестно" },
    };

    const dict = labels[userLang] || labels.en;
    return dict[String(value || "").toUpperCase()] || dict.UNKNOWN;
}

function labelTimeframe(value) {
    const labels = {
        en: { "1m": "1 min", "5m": "5 min", "15m": "15 min" },
        uk: { "1m": "1 хв", "5m": "5 хв", "15m": "15 хв" },
        es: { "1m": "1 min", "5m": "5 min", "15m": "15 min" },
        de: { "1m": "1 min", "5m": "5 min", "15m": "15 min" },
        ru: { "1m": "1 мин", "5m": "5 мин", "15m": "15 мин" },
    };

    const dict = labels[userLang] || labels.en;
    return dict[String(value || "")] || String(value || "");
}

function localizeReason(reason) {
    let text = String(reason || "");
    const replacements = {
        en: [
            ["NEWS_WAIT", "news pause"],
            ["NEUTRAL", "neutral"],
            ["BLOCK", "blocked"],
            ["BUY", "buy"],
            ["SELL", "sell"],
            ["WAIT", "wait"],
            ["ERROR", "error"],
            ["GO", "allowed"],
            ["Таймфрейми:", "Timeframes:"],
            ["Новини:", "News:"],
            ["Фільтр новин:", "News filter:"],
            ["ШІ", "AI"],
            ["пауза через новини", "news pause"],
            ["нейтрально", "neutral"],
            ["купівля", "buy"],
            ["продаж", "sell"],
            ["дозволено", "allowed"],
            ["заблоковано", "blocked"],
            ["немає даних", "no data"],
            ["подій високої важливості поруч немає", "no nearby high-impact events"],
            ["Symbol not found", "symbol not found"],
            ["No Account ID", "account is not ready"],
            ["Unsupported timeframe", "unsupported timeframe"],
            ["No trendbars returned", "historical data not received"],
            ["invalid_json_response", "invalid response"],
            ["all_models_unavailable", "all models unavailable"],
            ["1 хв", "1 min"],
            ["5 хв", "5 min"],
            ["15 хв", "15 min"],
        ],
        uk: [
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
            [" for ", " для "],
            ["1m", "1 хв"],
            ["5m", "5 хв"],
            ["15m", "15 хв"],
        ],
    };

    replacements.es = replacements.en.concat([
        ["allowed", "permitido"],
        ["blocked", "bloqueado"],
        ["buy", "compra"],
        ["sell", "venta"],
        ["wait", "esperar"],
        ["Timeframes", "Marcos temporales"],
        ["News", "Noticias"],
        ["Price", "Precio"],
        ["no data", "sin datos"],
        ["fresh", "fresco"],
        ["stale", "antiguo"],
        ["sec ago", "seg atrás"],
    ]);
    replacements.de = replacements.en.concat([
        ["allowed", "erlaubt"],
        ["blocked", "blockiert"],
        ["buy", "kauf"],
        ["sell", "verkauf"],
        ["wait", "warten"],
        ["Timeframes", "Zeitrahmen"],
        ["News", "Nachrichten"],
        ["Price", "Preis"],
        ["no data", "keine daten"],
        ["fresh", "frisch"],
        ["stale", "veraltet"],
        ["sec ago", "sek her"],
    ]);
    replacements.ru = replacements.en.concat([
        ["allowed", "разрешено"],
        ["blocked", "заблокировано"],
        ["buy", "покупка"],
        ["sell", "продажа"],
        ["wait", "ожидание"],
        ["Timeframes", "Таймфреймы"],
        ["News", "Новости"],
        ["Price", "Цена"],
        ["no data", "нет данных"],
        ["fresh", "свежая"],
        ["stale", "устарела"],
        ["sec ago", "сек назад"],
        ["1 min", "1 мин"],
        ["5 min", "5 мин"],
        ["15 min", "15 мин"],
    ]);

    (replacements[userLang] || replacements.en).forEach(([source, target]) => {
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
        forex: tr("forex"),
        crypto: tr("crypto"),
        commodities: tr("commodities"),
        watchlist: tr("watchlist"),
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
            const brokerUnavailable = brokerSymbolsLoaded && unavailablePairs.has(pairNorm);
            const priceText =
                brokerUnavailable
                    ? tr("noBroker")
                    : (price && typeof price.mid === "number" ? price.mid.toFixed(5) : "—");
            const unavailableClass = brokerUnavailable ? " unavailable" : "";
            const disabledAttr = brokerUnavailable ? " disabled" : "";
            const titleAttr = brokerUnavailable
                ? ` title="${escapeHtml(tr("noBrokerTitle"))}"`
                : "";

            sectionHtml += `
                <div class="pair-item${unavailableClass}">
                    <button class="pair-button${unavailableClass}" data-pair="${escapeHtml(pair)}"${disabledAttr}${titleAttr}>
                        <span class="pair-symbol">${escapeHtml(pair)}</span>
                        <span class="pair-price" data-pair="${pairNorm}">${priceText}</span>
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
        html += createSection(`⭐ ${tr("watchlist")}`, wl);
    }

    if (data.forex) {
        data.forex.forEach((session) => {
            html += createSection(session.title, session.pairs);
        });
    }

    if (data.crypto) html += createSection(`💎 ${tr("crypto")}`, data.crypto);
    if (data.commodities) html += createSection(`🥇 ${tr("commodities")}`, data.commodities);
    if (data.stocks) html += createSection(`📈 ${tr("stocks")}`, data.stocks);

    listsContainer.innerHTML = html;

    listsContainer.querySelectorAll(".pair-button").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            if (e.currentTarget.disabled) return;
            debouncedFetchSignal(e.currentTarget.dataset.pair);
        });
    });
}

function updatePairPriceInList(pairNorm, priceData) {
    const priceNodes = document.querySelectorAll(`.pair-price[data-pair="${pairNorm}"]`);
    if (!priceNodes.length) return;

    let priceText = "—";
    if (typeof priceData.mid === "number") {
        priceText = priceData.mid.toFixed(5);
    } else if (typeof priceData.bid === "number") {
        priceText = priceData.bid.toFixed(5);
    } else if (typeof priceData.ask === "number") {
        priceText = priceData.ask.toFixed(5);
    }

    priceNodes.forEach((priceNode) => {
        if (priceNode.textContent !== priceText) {
            priceNode.textContent = priceText;
        }
    });
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
    const previousText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "…";
    }

    try {
        const url = `${API_BASE_URL}/api/toggle_watchlist${buildQuery({ pair })}`;
        const response = await fetch(url, { method: "GET" });
        const res = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(res.error || `HTTP ${response.status}`);
        }

        if (res.success) {
            if (currentWatchlist.includes(pairNorm)) {
                currentWatchlist = currentWatchlist.filter((p) => p !== pairNorm);
            } else {
                currentWatchlist.push(pairNorm);
            }
            setCurrentWatchlist(currentWatchlist);

            try {
                const refreshed = await apiGet("/api/get_pairs");
                allData = refreshed || allData;
                setCurrentWatchlist(mergeWatchlists((refreshed && refreshed.watchlist) || []));
                applyPairMetadata(refreshed);
            } catch (refreshErr) {
                console.warn("Watchlist refresh failed, using local state:", refreshErr);
            }

            const searchInput = document.getElementById("searchInput");
            populateLists(allData, searchInput ? searchInput.value : "");
        } else {
            throw new Error(res.error || tr("favoriteNotUpdated"));
        }
    } catch (err) {
        console.error("Toggle favorite error:", err);
        const locallyEnabled = !currentWatchlist.includes(pairNorm);
        const nextWatchlist = locallyEnabled
            ? [...currentWatchlist, pairNorm]
            : currentWatchlist.filter((p) => p !== pairNorm);
        setCurrentWatchlist(nextWatchlist);

        const searchInput = document.getElementById("searchInput");
        populateLists(allData, searchInput ? searchInput.value : "");

        if (window.Telegram && tg && typeof tg.showAlert === "function") {
            tg.showAlert(tr("favoriteSavedLocal"));
        }
    } finally {
        if (button && button.textContent === "…") {
            button.disabled = false;
            button.textContent = previousText || "⭐";
        }
    }
}

async function fetchSignal(pair) {
    const pairNorm = normalizePair(pair);

    if (brokerSymbolsLoaded && unavailablePairs.has(pairNorm)) {
        lastSelectedPair = pair;
        currentSignalData = null;
        showLoader(false);
        signalOutput.innerHTML = `
            <div style="text-align:center; color:#ff9800; padding:10px;">
                ⚠️ ${escapeHtml(tr("noBrokerTitle"))}: ${escapeHtml(pair)}
            </div>
        `;
        setTimeout(() => {
            signalContainer.scrollIntoView({ behavior: "smooth" });
        }, 80);
        return;
    }

    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `<div style="text-align:center; padding:10px;">⏳ ${escapeHtml(tr("analyzing", { pair }))}</div>`;

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
                ${escapeHtml(tr("requestFailed"))}
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
        const rawVerdict = item?.verdict || "WAIT";
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

function labelSignalQuality(value) {
    const labels = {
        en: {
            strong: "strong",
            medium: "medium",
            weak: "weak",
            wait: "wait",
            "сильний": "strong",
            "середній": "medium",
            "слабкий": "weak",
            "чекати": "wait",
        },
        uk: {
            strong: "сильний",
            medium: "середній",
            weak: "слабкий",
            wait: "чекати",
            "сильний": "сильний",
            "середній": "середній",
            "слабкий": "слабкий",
            "чекати": "чекати",
        },
        es: {
            strong: "fuerte",
            medium: "media",
            weak: "débil",
            wait: "esperar",
            "сильний": "fuerte",
            "середній": "media",
            "слабкий": "débil",
            "чекати": "esperar",
        },
        de: {
            strong: "stark",
            medium: "mittel",
            weak: "schwach",
            wait: "warten",
            "сильний": "stark",
            "середній": "mittel",
            "слабкий": "schwach",
            "чекати": "warten",
        },
        ru: {
            strong: "сильный",
            medium: "средний",
            weak: "слабый",
            wait: "ждать",
            "сильний": "сильный",
            "середній": "средний",
            "слабкий": "слабый",
            "чекати": "ждать",
        },
    };

    const dict = labels[userLang] || labels.en;
    return dict[String(value || "").toLowerCase()] || dict.wait;
}

function renderDataStatus(signalData) {
    const status = signalData?.data_status || {};
    const items = [
        ["cTrader", status.ctrader],
        [tr("price"), status.price],
        [tr("calendar"), status.calendar],
        [tr("model"), status.ml],
        [tr("marketData"), status.market_data],
    ].filter(([, item]) => item && typeof item === "object");

    if (!items.length) return "";

    const rows = items.map(([name, item]) => {
        const ok = item.ok;
        const icon = ok === true ? "✅" : ok === false ? "⚠️" : "⏳";
        const color = ok === true ? "#26a69a" : ok === false ? "#ef5350" : "#94a3b8";
        const label = escapeHtml(localizeReason(item.label || tr("noData")));

        return `
            <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.06);">
                <span style="color:#e5e7eb;">${escapeHtml(name)}</span>
                <span style="color:${color}; text-align:right;">${icon} ${label}</span>
            </div>
        `;
    }).join("");

    return `
        <div style="margin:8px 0 6px; padding:8px 10px; border:1px solid rgba(255,255,255,0.08); border-radius:8px; background:rgba(255,255,255,0.02); font-size:12px; line-height:1.25;">
            <div style="font-weight:800; margin-bottom:4px; color:#ffffff;">${escapeHtml(tr("sourceCheck"))}</div>
            ${rows}
        </div>
    `;
}

function formatSignalAsHtml(signalData, exp) {
    if (signalData && signalData.unavailable_symbol) {
        return `
            <div style="text-align:center; color:#ff9800; padding:10px;">
                ⚠️ ${escapeHtml(tr("noBrokerTitle"))}: ${escapeHtml(signalData.pair || "")}
            </div>
        `;
    }

    if (!signalData || signalData.error) {
        return `
            <div style="text-align:center; color:#ef5350; padding:10px;">
                ❌ ${escapeHtml(tr("analysisError"))}
            </div>
        `;
    }

    const pair = escapeHtml(signalData.pair || tr("noData"));
    const price = signalData.price;
    const verdictText = escapeHtml(labelVerdict(signalData.verdict_text || "WAIT"));
    const score = Number.isFinite(Number(signalData.score)) ? Number(signalData.score) : 50;
    const rawSentiment = signalData.sentiment || "";
    const sentiment = rawSentiment ? escapeHtml(labelSentiment(rawSentiment)) : "";
    const reasons = Array.isArray(signalData.reasons) ? signalData.reasons : [];
    const tradeAllowed = Boolean(signalData.is_trade_allowed);
    const quality = escapeHtml(labelSignalQuality(signalData.signal_quality));

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
            : tr("noData");

    return `
        <div class="signal-header" style="text-align:center; font-size:1em; margin-bottom:6px;">
            <strong>${pair}</strong> <span style="color:#64748b; font-size:0.74em;">(${escapeHtml(tr("expiration"))}: ${escapeHtml(labelTimeframe(exp))})</span>
        </div>
        <div class="verdict-container" style="text-align:center; margin:6px 0 10px;">
            <div class="arrow" style="font-size:48px; line-height:0.95; display:block; margin-bottom:2px;">${arrow}</div>
            <div class="v-text ${cClass}" style="font-size:23px; font-weight:900; display:block; line-height:1;">${verdictText}</div>
            <div style="font-size:16px; color:#3390ec; font-family:monospace; margin-top:3px; display:block; line-height:1;">${safePrice}</div>
        </div>
        ${
            sentiment
                ? `<div class="ai-verdict" style="padding:5px 9px; border-radius:8px; text-align:center; font-weight:bold; margin:5px auto; border:1px solid; background:rgba(0,0,0,0.1); color:${rawSentiment === "GO" ? "#26a69a" : "#ef5350"}; width:fit-content; font-size:12px;">
                    ${rawSentiment === "GO" ? "✅" : "🚨"} ${escapeHtml(tr("news"))}: ${sentiment}
                   </div>`
                : ""
        }
        <div class="power-balance" style="display:flex; justify-content:space-around; margin:7px 0; font-weight:bold; text-align:center; font-size:13px;">
            <span style="color:#26a69a;">🐂 ${score}%</span>
            <span style="color:#ef5350;">🐃 ${100 - score}%</span>
        </div>
        ${renderTimeframeDetails(signalData)}
        ${renderDataStatus(signalData)}
        <div style="text-align:center; margin-top:5px; font-weight:bold; color:#f8fafc; font-size:13px;">
            🔎 ${escapeHtml(tr("signalQuality"))}: ${quality}
        </div>
        <div style="text-align:center; margin-top:5px; font-weight:bold; color:${tradeAllowed ? "#26a69a" : "#ef5350"}; font-size:13px;">
            ${tradeAllowed ? escapeHtml(tr("entryAllowed")) : escapeHtml(tr("entryNotRecommended"))}
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
