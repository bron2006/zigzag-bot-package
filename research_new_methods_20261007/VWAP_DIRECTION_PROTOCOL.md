# Діагностика напрямку власних VWAP-сигналів, 09.10.2026

Записано ДО розрахунку. Сигнали/історія вже відомі; SHORT-перевірка
народилася після негативного LONG-replay. Це НЕ сліпий OOS і НЕ дозвіл
змінити LONG-only executor. Runtime/реальні ордери не змінювати.

378 існуючих first pair-day намірів25.08–07.10, буквальні LIMIT/SL,
ті самі ASK/BID raw-кеші. Єдиний новий фактор — напрямок однакового
входу. Вхід на першому НОВОМУ ASK<=loggedLIMIT після signal+1s,
LONG за observedASK, SHORT за knownBID. Обидві сторони<=15s age,
crossed quotes -> unknown, а не пошук наступного вигіднішого входу.

Один незмінний symmetric bracket: risk=loggedLIMIT−loggedSL>0.
LONG SL=actualASK−risk, TP=actualASK+risk;
SHORT SL=actualBID+risk, TP=actualBID−risk. Обидва1:1 від actual entry.
Це діагностика сигналу, НЕ точний replay старого dynamicVWAP exit.
Не порівнювати новий LONG PF безпосередньо зі старим PF0.526, ніби
змінився лише напрям: новий TP/fill теж відрізняється від старого.

Long exits поBID, short поASK. Стоп перший; gap-stop за observedprice,
TP без позитивного price improvement. Одночасні timestamps: minBID/
maxASK для консервативного рішення обох сторін. Hard-end16UTC тільки
зі свіжою відповідною exit-side<=15s, інакше unknown. Event gap>120s
після signal -> unknown; це quality guard, не доказ loss реального feed.
Missing не замінювати нулями. Ніяких пагінацій/API/config/DB імпортів.

Комісія0.02ATR14 (тільки завершені M5 до сигналу), stress0.04ATR14
плюс0.02ATR14 негативного exit-slippage. ASK/BID уже включає спред.
Немає fee/grid/market/date оптимізації або відбору кращих символів.

Primary порівняння тільки на pairs з відомими ОБОМА результатами;
усі unknown/unfilled counts показати, не заховати. Окремо LONG/SHORT
meanR/PF, pairedSHORT−LONG, early до14.09 і late від14.09. Bootstrap
10000 цілих trading days, seed20261009. Gate для further research:
late SHORT stress PF>1, нижня95%CI SHORT meanR>0 та lowerCI paired
excess>0. Не скасовувати gate після результату; навіть PASS не forward
validation і не поправка за весь попередній шлях вибору стратегій.
