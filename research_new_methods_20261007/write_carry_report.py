"""Render public-read-only evidence, not an execution recommendation."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

def main():
    root=Path(__file__).parent
    snapshot=json.loads((root/'carry_snapshot.json').read_text(encoding='utf-8'))
    depth=json.loads((root/'carry_depth_snapshot.json').read_text(encoding='utf-8'))
    stamp=datetime.fromtimestamp(depth['end_server_ms']/1000,tz=timezone.utc).isoformat()
    lines=['# Новий напрям: строкова премія spot/futures','',f'Зріз глибини стакана: {stamp}. Це вже минулі ціни, не поточна пропозиція виконання.', '',
        'Публічні GET, без ключів, доступу до рахунка й ордерів. Фіксовані BTC/ETH та два квартальні USDT futures; три зрізи ASK spot/BID futures. Правила: CARRY_SCREEN_PROTOCOL.md.', '',
        '## Що знайшли','',
        'Додатна строкова премія існує. Її механізм відрізняється від прогнозування: довга spot-позиція й короткий строковий ф’ючерс однакового базового обсягу зменшують напрямлений ризик. Це не безризиковий арбітраж і не підтверджений дохід рахунка.', '',
        'Первинний stress-screen0.8% витрат пройшли BTC-грудень, ETH-грудень, BTC-березень у всіх трьох свіжих зрізах. ETH-березень має stale bookTicker й не допускається до висновку; null не означає збитковість.', '',
        '## Глибина, а не лише найкраща заявка','',
        '| Контракт | Spot-номінал для перевірки | Премія за середніми цінами стакана | Залишок після додаткового буфера0.8% | Річна проста оцінка на умовному2×капіталі |',
        '|---|---:|---:|---:|---:|']
    for row in depth['records']:
        if row['status']=='measured':
            lines.append(f"| {row['symbol']} | ${row['spot_notional_reference']} | {row['gross_gap']*100:.3f}% | {row['net_after_extra_008_buffer']*100:.3f}% | {row['simple_annualized_on_illustrative_2x_capital']*100:.3f}% |")
        else:
            lines.append(f"| {row['symbol']} | ${row['spot_notional_reference']} | {row['status']} | — | — |")
    best=next(r for r in depth['records'] if r['symbol']=='BTCUSDT_270326' and r['spot_notional_reference']==1000)
    lines += ['',f"Ілюстрація BTC-березень: приблизно {best['days_to_delivery']:.1f} днів до25.03/26.03.2027; $1000 spot-номіналу й умовний $1000 резерв дають математичний залишок близько ${best['net_after_extra_008_buffer']*1000:.2f} до погашення після додаткового0.8% буфера. Це не щомісячний заробіток і не гарантований прибуток. Точний delivery timestamp з exchangeInfo збережено у JSON.", '',
        'Фактичний entry-depth вже погіршує ціну. Додаткові0.8% зверху — свідомо консервативний сценарний буфер для невідомих комісій, виходу й інших витрат; не перевірений тариф. Він може частково перекривати вже враховане вхідне ковзання.', '',
        'Додаткова економічна ілюстрація після першого screen: за вимоги хоча б3% річних на умовний2×капітал жоден із цих зрізів не має достатнього запасу після буфера. Це не актуальна ставка безризикового інструмента й не попередньо заданий статистичний критерій.', '',
        '## Що заважає назвати це готовою стратегією','',
        '- Невідомі реальна доступність строкових futures користувачеві, комісії, settlement fee, collateral і мінімальні обсяги.',
        '- Різниця між кінцевою ціною продажу spot та розрахунковою ціною futures залишає basis/settlement-ризик.',
        '- Зростання ціни викликає збиток короткого futures і вимогу маржі; прибуток spot не обов’язково автоматично доступний для забезпечення. Умовний2×капітал не гарантує відсутності ліквідації.',
        '- Залишаються ризики біржі, USDT, обмежень переказів, збоїв і неодночасного виконання двох ніг.',
        '- Три короткі зрізи не доводять стійкість премії чи її доступність у майбутньому. Futures bookTicker transaction time може старіти на неактивному контракті; такий зріз виключено.', '',
        '## Рішення','',
        'Механізм із реальною вимірною премією знайдено, але цей зріз не виправдовує побудову торгового агента чи обіцянку суттєвого місячного доходу. Спочатку потрібні вимоги до капіталу/результату/ризику та фактичні умови доступного рахунка. Не вносити кошти й не відкривати hedge на підставі цього звіту.', '',
        'Поточний VWAP не змінено; жоден новий forward-тест чи моніторинг не запущено. Збережені скрипти дозволяють повторити одноразову публічну перевірку, але ціни треба перевіряти заново.', '',
        'Джерела: [Binance market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data), [Binance Spot](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market), [BIS: Crypto carry та ризик маржі/ліквідації](https://www.bis.org/publications/working-paper-1087-crypto-carry).']
    # Use the exact discovered delivery date rather than a manually typed calendar date.
    date=datetime.fromtimestamp(next(s['deliveryDate'] for s in snapshot['contracts'] if s['symbol']=='BTCUSDT_270326')/1000,tz=timezone.utc).date().isoformat()
    lines=[line.replace('до25.03/26.03.2027',f'до {date}') for line in lines]
    (root/'CARRY_SCREEN_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    provenance={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
                ('CARRY_SCREEN_PROTOCOL.md','carry_snapshot.json','carry_depth_snapshot.json','carry_screen.py')}
    (root/'carry_provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    print('Written CARRY_SCREEN_REPORT.md and carry_provenance.json')

if __name__=='__main__':main()
