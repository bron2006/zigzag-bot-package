// script.js

const API_BASE_URL = "https://zigzag-bot-package.fly.dev";

const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const historyContainer = document.getElementById("historyContainer"); // Новий елемент

let tg;
if (!window.Telegram || !window.Telegram.WebApp) {
    console.warn("Telegram WebApp object not found. Running in browser mode with mock data.");
    tg = { 
        themeParams: { bg_color: '#1a1a1a', text_color: '#ffffff' }, 
        initData: '',
        ready: function() {},
        expand: function() {}
    };
} else {
    tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    console.log("Telegram WebApp object is ready.");
}

let currentWatchlist = [];
let initData = tg.initData || '';

document.addEventListener('DOMContentLoaded', function() {
    // ... (код ініціалізації без змін) ...
});

// ... (функції toggleFavorite, createPairButton, populateLists без змін) ...

function fetchSignal(pair, assetType) {
    console.log(`fetchSignal called for pair: ${pair}`);
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую детальний аналіз для ${pair}...`;
    signalOutput.style.textAlign = 'left';
    historyContainer.innerHTML = ''; // Очищуємо стару історію
    Plotly.purge('chart');
    const oldNoChartDiv = document.getElementById('no-chart-info');
    if (oldNoChartDiv) oldNoChartDiv.remove();

    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}&initData=${encodeURIComponent(initData)}`;
    const mtaApiUrl = `${API_BASE_URL}/api/get_mta?pair=${pair}`;

    Promise.all([
        fetch(signalApiUrl).then(res => res.json()),
        fetch(mtaApiUrl).then(res => res.json())
    ])
    .then(([signalData, mtaData]) => {
        if (signalData.error) {
            // ... (обробка помилок без змін)
            return;
        }

        // ... (код для відображення основного сигналу без змін) ...
        
        if (signalData.history && signalData.history.dates && signalData.history.dates.length > 0) {
            drawChart(pair, signalData.history);
        } else {
            // ... (обробка відсутності графіка без змін) ...
        }
        
        // --- ПОЧАТОК ЗМІН: Запит та відображення історії ---
        if (initData) { // Показуємо історію, лише якщо користувач авторизований
            fetchHistory(pair);
        }
        // --- КІНЕЦЬ ЗМІН ---

        showLoader(false);
    })
    .catch(err => {
        // ... (обробка помилок без змін) ...
    });
}

// --- НОВЕ: Функція для отримання та відображення історії ---
function fetchHistory(pair) {
    const historyApiUrl = `${API_BASE_URL}/api/signal_history?pair=${pair}&initData=${encodeURIComponent(initData)}`;
    fetch(historyApiUrl)
        .then(res => res.json())
        .then(historyData => {
            if (historyData && historyData.length > 0) {
                displaySignalHistory(historyData);
            }
        })
        .catch(err => console.error("Error fetching signal history:", err));
}

function displaySignalHistory(history) {
    let html = '<div class="history-title">Історія сигналів</div>';
    html += '<table class="history-table"><thead><tr><th>Час</th><th>Ціна</th><th>Сигнал</th><th>Сила (Бики)</th></tr></thead><tbody>';

    history.forEach(item => {
        const date = new Date(item.timestamp.replace(' ', 'T') + 'Z');
        const formattedDate = `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')} ${date.getDate().toString().padStart(2, '0')}.${(date.getMonth() + 1).toString().padStart(2, '0')}`;
        const signalClass = `signal-${item.signal_type.toLowerCase()}`;
        const price = item.price ? item.price.toFixed(4) : 'N/A';

        html += `
            <tr>
                <td>${formattedDate}</td>
                <td>${price}</td>
                <td class="${signalClass}">${item.signal_type}</td>
                <td>${item.bull_percentage}%</td>
            </tr>
        `;
    });

    html += '</tbody></table>';
    historyContainer.innerHTML = html;
}
// --- КІНЕЦЬ ЗМІН ---

// ... (решта функцій: drawChart, showLoader, getAssetType без змін) ...