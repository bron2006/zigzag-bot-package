// webapp/script.js
// Примітка: API_BASE_URL більше не потрібен, оскільки всі запити йдуть на той самий домен
const loader = document.getElementById("loader");
const listsContainer = document.getElementById("listsContainer");
const signalOutput = document.getElementById("signalOutput");
const liveSignalsContainer = document.getElementById('liveSignalsContainer');
const signalContainer = document.getElementById('signalContainer');

let tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

let currentTimeframe = '1m';
let lastSelectedPair = null;

const debouncedFetchSignal = debounce(fetchSignal, 300);

document.addEventListener('DOMContentLoaded', function() {
    showLoader(true);
    // Завантажуємо статичні пари (припускаємо, що вони є в config.py, який тепер читає worker)
    // і статус сканерів
    Promise.all([
        fetch('/api/scanner/status').then(res => res.json()),
        // Ми можемо додати маршрут /get_assets до worker, якщо потрібно
        // поки що використовуємо статичні дані
    ]).then(([statusData]) => {
        updateScannerButtons(statusData);
        populateStaticLists(); // Функція для відображення статичних списків
        showLoader(false);
    }).catch(err => {
        signalOutput.innerHTML = `<h3 style="color: #ef5350;">❌ Помилка завантаження.</h3><p>${err.message}</p>`;
        showLoader(false);
    });
    
    document.getElementById('scannerControls').addEventListener('click', (event) => {
        if (event.target.classList.contains('scanner-button')) {
            const scannerType = event.target.dataset.type;
            toggleScanner(scannerType);
        }
    });

    const eventSource = new EventSource(`/api/signal-stream`);
    
    eventSource.onmessage = function(event) {
        const signalData = JSON.parse(event.data);
        displayLiveSignal(signalData);
    };
    
    eventSource.onerror = function(err) {
        console.error("EventSource failed:", err);
    };
});

function toggleScanner(type) {
    const button = document.querySelector(`.scanner-button[data-type="${type}"]`);
    button.textContent = '...';

    fetch('/api/scanner/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: type })
    })
    .then(res => res.json())
    .then(data => {
        if(data.success) {
            updateScannerButtons(data.newState);
        }
    });
}

function updateScannerButtons(status) {
    for (const type in status) {
        const button = document.querySelector(`.scanner-button[data-type="${type}"]`);
        if (button) {
            const isEnabled = status[type];
            button.textContent = `${isEnabled ? '✅' : '❌'} ${button.dataset.label}`;
            button.classList.toggle('enabled', isEnabled);
        }
    }
}

function displayLiveSignal(signalData) {
    const signalDiv = document.createElement('div');
    signalDiv.className = 'live-signal';
    
    const verdict = signalData.verdict_text || '...';
    const pair = signalData.pair || 'N/A';
    const score = signalData.bull_percentage || 50;
    
    let signalClass = 'neutral';
    if (score >= 65) signalClass = 'buy';
    if (score <= 35) signalClass = 'sell';
    
    signalDiv.classList.add(signalClass);
    signalDiv.innerHTML = `<strong>${verdict}</strong> по ${pair} (Бики: ${score}%)`;
    
    liveSignalsContainer.prepend(signalDiv);
    
    setTimeout(() => {
        signalDiv.classList.add('fade-out');
        setTimeout(() => signalDiv.remove(), 500);
    }, 15000);
}

function fetchSignal(pair) {
    lastSelectedPair = pair;
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую свіжі дані для ${pair}...`;
    signalOutput.style.textAlign = 'left';
    
    fetch(`/api/signal?pair=${pair}`)
        .then(res => {
            if (!res.ok) {
                return res.json().then(errData => { throw new Error(errData.error || `HTTP ${res.status}`) });
            }
            return res.json();
        })
        .then(signalData => {
            let html = formatSignalAsHtml(signalData);
            signalOutput.innerHTML = html;
        })
        .catch(err => {
            signalOutput.innerHTML = `❌ Помилка: ${err.message}`;
        })
        .finally(() => {
            signalContainer.scrollIntoView({ behavior: 'smooth' });
            showLoader(false);
        });
}

// ... (решта функцій з script.js: populateStaticLists, formatSignalAsHtml, debounce, showLoader і т.д.)
// Вам потрібно буде реалізувати populateStaticLists, щоб вона малювала списки пар
// так само, як це робилося раніше, але можна взяти їх з локального масиву
// або зробити запит до worker'а за ними.