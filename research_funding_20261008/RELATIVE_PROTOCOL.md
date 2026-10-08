# Другий новий screen: відносний momentum BTC/ETH

Зафіксовано після результату funding-carry, ДО першого розрахунку цього
правила. Історія відома; не називати blind OOS і не забувати весь шлях
невдалих гіпотез. Жодного grid search або вибору кращого horizon.

Одне правило: на початку UTC-місяця long perpetual активу з більшим
12-місячним spot-return, short іншого. Визначаємо рейтинг по Close
місяця t−2: повний місяць buffer. Рівність -> cash. Gross100% NAV:
50% long і50% short, collateral половина NAV кожній стороні окремо.
Ребаланс/ліквідація щомісяця,1000 умовного стартового NAV на блок.
Різні BTC/ETH beta та кореляція: це НЕ безризикова/market-neutral угода.

Дані вже отримані2024–30.09.2026, funding із фактичними markPrice.
2024 early;2025–30.09.2026 late. Витрати futures0.1%/сторону,
stress0.2%. Long платить positive funding; short отримує, negative
funding змінює знак. Daily Open/Close — проксі execution, не BID/ASK.

Маржинальний stress: long за daily markLow, short за markHigh,
позитивний funding поточної доби не допомагає до екстремуму, від'ємний
відняти. Collateral/notional>=10% кожної сторони, інакше screen FAIL.
Це не фактичний liquidation engine або тариф користувача.

Контролі на тих самих днях/обсягах: cash; зворотний рейтинг;
постійно longBTC/shortETH. Останній відділяє правило від випадку
«BTC просто довго переганяв ETH». Gate: late stress net>0, жодного
margin порушення, нижня95% paired circular bootstrap3months10000
seed20261008 log-excess над постійним BTC/ETH-control>0. Контроль теж
показати з margin-порушеннями; нездійсненний контроль не доказ edge.
Додатний raw return без gate — лише описовий результат.

Мотивація cross-sectional momentum, не доказ на двох криптоактивах:
https://www.aqr.com/Insights/Datasets/Value-and-Momentum-Everywhere-Factors-Monthly
Ніяких приватних API, ордерів, змін працюючих ботів або деплою.
