# Funding-carry: нова структурна гіпотеза, 08.10.2026

Протокол до fetch/розрахунку. НЕ повтор квартальних futures-зрізів:
тут perpetual і фактична історія funding, без прогнозування ціни.
BTCUSDT/ETHUSDT фіксовані, жодного відбору переможця чи grid search.
2024–30.09.2026,2024 ранній блок,2025–30.09.2026 пізній.

Окремо для кожного активу умовний NAV1000. На початку кожного UTC-місяця
50% NAV у spot, решта collateral USD-M short ТІЄЇ Ж кількості монет.
Закриття обох сторін наприкінці місяця й новий збалансований кошик
наступного місяця; не вигадувати перекази/ліквідації між цими моментами.
Funding тільки строго після входу й до місячного виходу; markPrice*qty*
fundingRate для SHORT, включно з від'ємними виплатами. Funding не
відома наперед і не гарантована. Cash не приносить відсотків.

Spot/perpetual daily Open/Close — проксі фактичної ціни, НЕ BID/ASK.
База all-in spot0.15%/сторону, futures0.10%; stress удвічі.
Фактичний тариф/мінімальні обсяги/доступ користувача невідомі.
Кінцева ліквідація й щомісячний turnover включені. Не сумувати
fundingRate і називати це прибутком на весь капітал.

Щоденний mark High — песимістичний stress collateral: credit тільки
funding до початку доби; усі від'ємні виплати цієї доби відняти,
позитивні не додавати до intraday-margin stress. Порогове утримання
margin>=10% short-notional при High — ДОСЛІДНИЦЬКИЙ запас, не реальна
maintenance margin Binance й не гарантія відсутності ліквідації.
Будь-яке порушення -> FAIL: не продовжувати equity після такого дня
як реалізовний результат. Показати potential/unconstrained окремо.

До подальшого дослідження: ОБИДВА late stress net>0; жодного margin
порушення; нижня95% CI середнього місячного log-return>0 проти cash0,
circular blocks3months,10000 повторів, seed20261008. Показати всі
33 місяці, funding/turnover/basis окремо, суми для1000 і невизначеність.
Денні і місячні close/DD не є доведеною intraday NAV-просадкою.

Raw public GET fundingRate/klines/markPriceKlines, без private API,
ключів, ордерів, env/config/Supabase. Spot із наявного raw-кешу з hash.
Максимум60s whole fetch-child на актив; cache кожного активу окремо,
існуючі файли не переписувати. Missing/gap/markPrice0 -> відмова,
не заповнення нулями. Funding gap>12h -> quality FAIL, не припущення
незмінного8h розкладу. Останні події мають досягати фінальних12h.

Механізм: https://www.binance.com/en/support/faq/detail/360033525031
API: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History
