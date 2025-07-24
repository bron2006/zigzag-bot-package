// [...початок твого коду не змінено...]

// --- ПОЧАТОК ОНОВЛЕННЯ fetchSignal() ---
function fetchSignal(pair, assetType) {
    console.log(`fetchSignal called for pair: ${pair}`);
    showLoader(true);
    signalOutput.innerHTML = `⏳ Отримую детальний аналіз для ${pair}...`;
    signalOutput.style.textAlign = 'left';
    Plotly.purge('chart');

    const signalApiUrl = `${API_BASE_URL}/api/signal?pair=${pair}`;
    const mtaApiUrl = `${API_BASE_URL}/api/get_mta?pair=${pair}`;

    Promise.all([
        fetch(signalApiUrl).then(res => res.json()),
        fetch(mtaApiUrl).then(res => res.json())
    ])
    .then(([signalData, mtaData]) => {
        if (signalData.error) {
            signalOutput.innerHTML = `❌ Помилка: ${signalData.error}`;
            signalOutput.style.textAlign = 'center';
            showLoader(false);
            return;
        }

        const arrow = signalData.bull_percentage >= 50 ? '⬆️' : '⬇️';
        const mainReason = signalData.reasons && signalData.reasons.length > 0
            ? signalData.reasons[0]
            : 'Основна причина відсутня';

        const supportText = signalData.support ? signalData.support.toFixed(4) : 'N/A';
        const resistanceText = signalData.resistance ? signalData.resistance.toFixed(4) : 'N/A';
        const reasonsList = signalData.reasons.map(r => `<li>${r}</li>`).join('');
        let candleHtml = signalData.candle_pattern?.text ? `<div style="margin-bottom:10px"><strong>Свічковий патерн:</strong><br>${signalData.candle_pattern.text}</div>` : '';
        let volumeHtml = signalData.volume_analysis ? `<div style="margin-bottom:10px"><strong>Аналіз об'єму:</strong><br>${signalData.volume_analysis}</div>` : '';

        let mtaHtml = '';
        if (Array.isArray(mtaData) && mtaData.length > 0) {
            mtaHtml += '<div class="mta-container">';
            mtaHtml += '<strong>Мульти-таймфрейм аналіз (MTA):</strong>';
            mtaHtml += '<table class="mta-table"><tr>';
            mtaData.forEach(item => { mtaHtml += `<th>${item.tf}</th>`; });
            mtaHtml += '</tr><tr>';
            mtaData.forEach(item => {
                const signalClass = item.signal.toLowerCase();
                mtaHtml += `<td class="${signalClass}">${item.signal}</td>`;
            });
            mtaHtml += '</tr></table></div>';
        }

        signalOutput.innerHTML = `
            <div style="font-size: 38px; text-align: center; margin-bottom: 8px;">${arrow}</div>
            <div style="text-align: center; margin-bottom: 12px;"><strong>Причина:</strong> ${mainReason}</div>
            <div style="margin-bottom: 10px;"><strong>${signalData.pair}</strong> | Ціна: ${signalData.price.toFixed(4)}</div>
            <div style="margin-bottom: 10px;"><strong>Баланс сил:</strong><br>🐂 Бики: ${signalData.bull_percentage}% ⬆️ | 🐃 Ведмеді: ${signalData.bear_percentage}% ⬇️</div>
            ${candleHtml}
            <div style="margin-bottom: 10px;"><strong>Рівні S/R:</strong><br>Підтримка: ${supportText} | Опір: ${resistanceText}</div>
            ${volumeHtml}
            <div><strong>Ключові фактори:</strong><ul style="margin: 5px 0 0 20px; padding: 0;">${reasonsList}</ul></div>
            ${mtaHtml}
        `;
        
        if (signalData.history && signalData.history.dates) drawChart(pair, signalData.history);
        showLoader(false);
    })
    .catch(err => {
        console.error(`Error fetching signal for ${pair}:`, err);
        signalOutput.innerHTML = `❌ Помилка: ${err.message}`;
        signalOutput.style.textAlign = 'center';
        showLoader(false);
    });
}
// --- КІНЕЦЬ ОНОВЛЕННЯ fetchSignal() ---

// [...весь твій код після fetchSignal — не змінюється...]
