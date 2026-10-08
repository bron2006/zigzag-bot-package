"""Offline attribution of fixed price-only trend rules, not parameter search."""
import json
import math
from pathlib import Path
import numpy as np
from daily_trend import load_history, simulate, SYMBOLS
from exposure_check import metrics

FOLDER=Path(__file__).parent

def trade_cycles(df,fee):
    active=False
    cycles=[]
    entry=None
    for row in df.itertuples(index=False):
        if row.position and not active:
            entry=dict(date=str(row.date.date()),price=row.Open)
            active=True
        elif not row.position and active:
            factor=(1-fee)**2*row.Open/entry['price']
            cycles.append(dict(entry_date=entry['date'],exit_date=str(row.date.date()),factor=factor,net_return=factor-1,final_liquidation=False))
            active=False
    if active:
        row=df.iloc[-1]
        factor=(1-fee)**2*row.Close/entry['price']
        cycles.append(dict(entry_date=entry['date'],exit_date=str(row.date.date()),factor=factor,net_return=factor-1,final_liquidation=True))
    return cycles

def concentration(cycles):
    factors=[c['factor'] for c in cycles]
    best=sorted((math.log(f) for f in factors if f>1),reverse=True)
    positive=sum(best)
    total=sum(math.log(f) for f in factors)
    return dict(total_return=math.expm1(total),positive_cycles=len(best),negative_cycles=int(sum(f<1 for f in factors)),
        largest_positive_log_share=best[0]/positive if best else None,
        top3_positive_log_share=sum(best[:3])/positive if best else None,
        return_without_best_cycle=math.expm1(total-sum(best[:1])),
        return_without_best3_cycles=math.expm1(total-sum(best[:3])))

def main():
    results=[]
    lines=['# Повільний spot-тренд на капіталі $1000: перевірка концентрації','',
        'Це масштабування історичної моделі, не рекомендація вкладати$1000 і не прогноз. Правила незмінні, без плеча; ордерів/forward-тесту немає.', '',
        '| Актив | Витрати на бік | Прибуток2024–30.09.2026 | Макс.просадка | Завершені цикли | Без найкращого циклу | Без3 найкращих |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for symbol in SYMBOLS:
        history=load_history(FOLDER/'public_daily'/f'{symbol}_1d.json')
        late=history[history.date>='2024-01-01']
        for fee in (.001,.003):
            measured,curve=simulate(late,fee)
            cycles=trade_cycles(late,fee)
            detail=concentration(cycles)
            assert np.isclose(math.prod(c['factor'] for c in cycles),curve[-1],rtol=1e-12,atol=1e-12)
            years=[]
            previous=1.
            for year in sorted(late.date.dt.year.unique()):
                indices=np.flatnonzero(late.date.dt.year.to_numpy()==year)
                subcurve=curve[indices]/previous
                years.append(dict(year=int(year),days=len(indices),return_over_calendar_segment=float(subcurve[-1]-1),
                    max_drawdown_with_local_reset=metrics(subcurve)['max_drawdown']))
                previous=curve[indices[-1]]
            results.append(dict(symbol=symbol,fee=fee,metrics=measured,cycles=cycles,concentration=detail,years=years,
                hypothetical_1000_end_value=1000*curve[-1],historical_peak_to_trough_fraction=measured['max_drawdown']))
            lines.append(f"| {symbol} | {fee*100:.1f}% | {measured['total_return']*100:+.1f}% | {measured['max_drawdown']*100:.1f}% | {len(cycles)} | {detail['return_without_best_cycle']*100:+.1f}% | {detail['return_without_best3_cycles']*100:+.1f}% |")
    lines += ['', '## Календарні частини, базові витрати','', '| Актив | Рік | Днів | Результат зі збереженням позиції |','|---|---:|---:|---:|']
    for result in results:
        if result['fee']==.001:
            for year in result['years']:
                lines.append(f"| {result['symbol']} | {year['year']} | {year['days']} | {year['return_over_calendar_segment']*100:+.1f}% |")
    lines += ['', '## Практичний висновок','',
        'Гіпотеза має позитивний історичний сумарний результат, але не регулярну місячну зарплату. Вилучення переможців — лише ретроспективна чутливість: наперед їх не можна впізнати. Великий внесок кількох рухів типовий для тренду й не є самостійним доказом відсутності стратегії.', '',
        'Попередня перевірка не довела переваги над matched пасивним утриманням; цей аналіз не скасовує її висновок. Просадки великі, а допустима втрата користувача поки невідома. На$1000 не слід приховувати ризик плечем або називати прибуток за2.75року місячним доходом.', '',
        'До реального запуску немає допуску. Якщо потрібний саме дослідницький forward-тест, лише окремий paper-процес із фіксованими правилами й точним журналом; його ще не створено й не запущено. Реальні гроші не використовуються.', '',
        'Дані: public_daily/BTCUSDT_1d.json та ETHUSDT_1d.json. JSON результатів: trend_concentration_results.json. Перевірено добуток net-циклів проти незалежної equity-функції у двох активах/двох сценаріях витрат.']
    (FOLDER/'trend_concentration_results.json').write_text(json.dumps(dict(results=results,not_independent_oos=True),indent=2,allow_nan=False),encoding='utf-8')
    (FOLDER/'TREND_CONCENTRATION_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ('symbol','fee','concentration','years')} for r in results],indent=2))

if __name__=='__main__':main()
