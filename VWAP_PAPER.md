# Паперовий журнал VWAP — реалізовано 08.10.2026

Нові модулі vwap_paper.py і vwap_paper_bridge.py інтегровані в
READ-ONLY-гілку vwap_executor.py. Вони не імпортують брокерські API,
config чи Supabase. Журнал: logs/vwap_paper.sqlite3, SQLite/WAL.
Файл .lock забороняє двом процесам одночасно вести один журнал.

## Правила й точність

- Один незмінний намір на symbol/session; pending → open → closed,
  або expired/cancelled/unknown. Повторний poll не нова угода.
- Лише LONG LIMIT, записаний SL і відома після закриття M5-бару VWAP.
  Вікно намірів останні4години сесії. Pending також займає один із
  max-open slots, значення взято з чинного executor config.
  Відхилені через ліміт наміри також збережені як skipped_capacity.
- Fill лише за спостереженим ASK<=LIMIT, строго після наміру, за LIMIT
  без позитивного ковзання. BID/ASK не старші15s; часткові ticks
  об’єднуються зі своїми часовими мітками, не з одним спільним віком.
- STOP має пріоритет. Вихід VWAP при новому BID>=останній спостережений
  VWAP; вихід за BID, не за бажаною ціною target. VWAP, відомий лише
  пізніше, не застосовується до минулих quotes.
- Hard-session-end використовує останній BID не старший15s до кінця;
  немає ціни — unknown. Expired/unfilled теж вимагає котирувань, а не
  мовчання feed. Manual stop скасовує pending та закриває open лише
  за свіжим BID, інакше unknown.
- Втрата з’єднання, переповнення обмеженої черги або перезапуск роблять
  активні результати unknown. Відсутні ціни не замінюються нульовим PnL.
- Fee proxy0.02ATR14 за повний цикл, ATR відомий до наміру. Результат
  у R відносно LIMIT−SL. Обсяг зберігається для аудиту, але валютна
  конвертація, баланс/депозит, risk-manager і фактичний тариф не
  симулюються. Це не грошовий PnL акаунта і не доказ реального fill.

Quotes мають receipt-time місцевого потоку, не підтверджену латентність
брокерського виконання; модель не відтворює queue position, market depth,
partial fills чи гарантовану ціну MARKET. Strategy-version фіксована:
vwap-paper-quote-market-v1. Реальна торгова гілка не змінювалася; її
старий bar-range exit ще не прирівняний до цієї quote-моделі.

## Спільний механізм live-paper і replay

scripts/vwap_paper_replay.py відтворює нормалізовані JSONL-події signal,
target, quote, gap, advance, halt тим самим PaperJournal, що й bridge.
Це прибирає різні формули lifecycle у новому paper/replay. Старі
vwap_long_only_backtest.py та історичні CSV не переписані/не проголошені
виправленими. Повне порівняння старих стратегій — окремий етап.

Replay вимагає нового output-файлу й відмовляється торкатися production
журналу. Неправильний порядок timestamps відхиляється. Тести порівнюють
результат тих самих подій у bridge та replay.

## Перевірки та застосування

37 нових тестів: lifecycle, time guards, stale quotes, стоп/gap, комісія,
unknown, рестарт, single-writer, idempotency, bounded queue, READ-ONLY
guard і збіг live-paper/replay. Регресія executor/watchdog/reliability
перевіряється окремо з DATABASE_URL=sqlite:///:memory:, не Supabase.

Статус без імпорту бота:
`python scripts/vwap_paper_status.py`

Код не стає активним у вже запущеному Python-процесі автоматично.
Контрольоване застосування до підтвердженого SYSTEM-worker:
`scripts/reload_vwap_paper_fix.ps1` у PowerShell адміністратора.
Скрипт спершу перевіряє source-marker, explicit READ_ONLY=true,
ідентичність supervisor/PID/start-time і старий readonly-stdout; лише
потім завершує один worker. Перезапуск робить чинний supervisor.
Після перевіряються новий PID/marker, readonly-stdout, ready-журнал
та свіжий heartbeat. Він не реєструє нову задачу, не стартує дубль,
не змінює .env/торгові перемикачі. -DryRun нічого не завершує.

На момент написання цього документа live-застосування не підтверджене:
поточний сеанс не підвищений. -DryRun перевірив supervisor3920 і worker10364
(08.10.2026 16:29:57local), без завершення процесів. Старий stdout має
Read-only:True, але ще не має paper-marker. Production-журнал ще не існує. Не казати,
що forward-тест уже працює, лише за наявністю коду.
