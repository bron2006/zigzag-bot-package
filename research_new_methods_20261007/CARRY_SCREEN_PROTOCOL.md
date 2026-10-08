# Перевірка строкової премії без прогнозування ціни

Зафіксовано до bookTicker-цін. Це публічний screen, не дозвіл торгувати.
Фіксований набір: BTCUSDT/ETHUSDT, CURRENT_QUARTER/NEXT_QUARTER,
лише TRADING строкові USDT futures із exchangeInfo. Не perpetual funding.
Три послідовні зрізи публічних ASK spot / BID futures. Не остання ціна.
Однаковий обсяг базового активу, linear USDT settlement. Gross gap
(futures BID−spot ASK)/spot ASK; annualized просте gap*365.25/days,
не складний дохід і не прогноз повторного інвестування.

Сценарний повний бюджет витрат0.4% і stress0.8% spot-notional, не тарифи
акаунта. Окремо показати break-even сукупні витрати. За ілюстративного
total capital2*spot-notional дохід удвічі менший; це НЕ захист від
ліквідації й не розрахований margin buffer. Фактична доступність продукту,
комісія/settlement, collateral, slippage й кінцевий basis-risk невідомі.
Вік котирування futures до15s, весь зріз до15s; snapshot stale відхилити.

Тільки кандидат для наступної перевірки, якщо у всіх трьох зрізах gap
покриває stress0.8%. Інакше не будувати trading executor. Перевірка
економіки не дозволяє оголосити безризиковий чи зафіксований прибуток:
ліквідація, біржа, USDT, різні ціни кінцевого розрахунку зберігають ризик.
Немає API keys, private endpoints, ордерів, переказів або депозитів.
