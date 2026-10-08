# Два нові пошуки, завершені 08.10.2026

Це аналіз публічних даних, НЕ брокерські угоди. Працюючі боти, конфіг,
прапорці рахунків, Supabase і Fly не змінювалися. Нових процесів немає.
Мета — перевірка інших механізмів, не перебір параметрів VWAP.

## 1. Funding-carry зі щомісячним відновленням хеджу

Spot long + perpetual short однакової кількості BTC або ETH. На умовному
капіталі1000 половина spot, половина collateral; НЕ1000 на кожну сторону.
Фактичні positive та negative funding, basis, усі entry/exit fees.
По3012 виплат і1004 дні2024–30.09.2026 на актив; raw збережено,
source/protocol hashes у results_v1.json. Правила: PROTOCOL.md.

Січень2025–вересень2026, кожен актив окремо зі стартом1000:

| Актив | Funding | Зміна basis | Витрати | Підсумок | Stress net |
|---|---:|---:|---:|---:|---:|
| BTC | +37.39 | +0.16 | −52.23 | −14.69 | −65.21 |
| ETH | +34.73 | +0.11 | −52.46 | −17.61 | −68.20 |

Суми умовні USD/USDT ЗА21МІСЯЦЬ, не щомісяця. За2024 net BTC+32.88,
ETH+39.14 — ранній прибуток не зберігся в пізнішому режимі. Late лише
5/21 прибуткових місяців BTC,4/21 ETH. Критерій обох активів FAIL.
Застава в stress-screen не порушена, але це не доказ реальної
відсутності liquidation/ADL/API/transfer/USDT/exchange-risk.

Висновок вузький: саме ALWAYS-хедж з MONTHLY-перебудовою не пройшов.
Не стверджувати, що всі funding-підходи збиткові, або що можливість
зменшення turnover вже перевірена. Іншу політику записати до тесту;
попередні результати не переписувати і не називати нову перевірку OOS.

## 2. Відносний12-місячний momentum BTC/ETH

Long сильніший/short слабший,50% notional на сторону; рішення за
Close t−2, повний місяць buffer, усі фактичні funding. Протокол
RELATIVE_PROTOCOL.md ДО розрахунку, relative_results_v1.json.
Це не гарантовано market-neutral: beta двох монет змінюється.

Січень2025–вересень2026:

| Модель | Base net | Stress net |
|---|---:|---:|
| Фіксоване ranking-правило | −13.37% | −17.00% |
| Зворотне ranking-правило, контроль | −5.48% | −9.39% |
| Постійно longBTC/shortETH, контроль | −18.16% | −21.60% |

Денна close-просадка ranking42.98%/43.53% base/stress. Парна нижня95%
межа log-excess над fixedBTC-control негативна. Late gate FAIL.
Зворотне правило не новий підібраний переможець і теж негативне.

## Перевірки та межі

19 нових unit-tests: fee, sign, entry/exits, fundingMark, basis,
buffer/ranking, short/long collateral extremes, private API forbidden.
Незалежні cash-формули:132 month funding-checks і396 relative-leg-checks,
максимальна різниця<1e-8USD. Повтор: python -m research_funding_20261008.audit.
Unit tests: python -m unittest discover -s tests -p 'test_*screen.py'.

Daily Open/Close і all-in витрати — модель, не історичні executable
BID/ASK та не реальний тариф. Margin10% — дослідницький stress threshold,
не maintenance table брокера. Відомі21 late-місяць не blind OOS;
bootstrap не виправляє весь попередній вибір гіпотез. Не деплоїти
торгового агента і не підвищувати плече за цими результатами.

Механізм та API: https://www.binance.com/en/support/faq/detail/360033525031
https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History
Мотивація relative ranking, НЕ доказ на крипті:
https://www.aqr.com/Insights/Datasets/Value-and-Momentum-Everywhere-Factors-Monthly
