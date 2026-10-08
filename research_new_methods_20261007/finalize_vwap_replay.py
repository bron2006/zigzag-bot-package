"""Recompute entirely offline from checkpoints, then build an auditable daily report."""
from collections import Counter
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import re
from full_tick_replay import FOLDER, session_data, tick_replay, write_results
from replay_vwap import ROOT, statistics

def fmt(value, places=3):
    return '—' if value is None else f'{value:.{places}f}'

def main():
    prior=json.loads((FOLDER/'vwap_tick_results.json').read_text(encoding='utf-8'))
    if not prior['summary']['all_processed']:
        raise RuntimeError('Download has not completed; no final report produced')
    m5=json.loads((FOLDER/'vwap_replay_results.json').read_text(encoding='utf-8'))
    inventory=json.loads((FOLDER/'vwap_intentions_inventory.json').read_text(encoding='utf-8'))
    orders=sorted([r for r in m5['records'] if r['units']=='literal' and r['stress']==1],key=lambda r:(r['day'],r['symbol']))
    records,hashes=[],{}
    for order in orders:
        path=FOLDER/'vwap_replay_ticks'/f"{order['day']}_{order['symbol']}.json.gz"
        if not path.exists():
            for stress in (1,2):
                records.append(dict(symbol=order['symbol'],day=order['day'],stress=stress,status='unavailable'))
            continue
        hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            data=json.load(stream)
        expected_end=int(datetime.fromisoformat(order['day']+'T16:00:00+00:00').timestamp()*1000)
        if data['start_ms']!=order['signal_ts']*1000-60000 or data['end_exclusive_ms']!=expected_end or not data['complete_pages']:
            raise ValueError('Cached quote bounds or pagination do not match protocol')
        for quotes in data['streams'].values():
            times=[t['timestamp_ms'] for t in quotes]
            if times!=sorted(times) or any(not data['start_ms']<=t<expected_end for t in times):
                raise ValueError('Unsorted or out-of-window quotes')
        completed,vwaps,atr=session_data(order['symbol'],order['day'],order['signal_ts'])
        for stress in (1,2):
            measured=tick_replay(order,data['streams'],completed,vwaps,.02*atr*stress,.02*atr if stress==2 else 0)
            records.append(dict(symbol=order['symbol'],day=order['day'],stress=stress,
                signal_ts=order['signal_ts'],limit=order['limit'],stop=order['stop'],
                source=order['source'],line=order['line'],commission_price=.02*atr*stress,
                extra_exit_slippage_price=.02*atr if stress==2 else 0,**measured))
    write_results(records,hashes,len(orders),len(orders))
    output=json.loads((FOLDER/'vwap_tick_results.json').read_text(encoding='utf-8'))
    output['offline_recomputed_after_synthetic_tests']=True
    gross=[dict(r,r=r['r']+r['commission_price']/(r['limit']-r['stop'])) if r['status']=='filled' else r
           for r in records if r['stress']==1]
    output['gross_before_commission']=statistics(gross)
    output['input_sha256']={name:hashlib.sha256((FOLDER/name).read_bytes()).hexdigest() for name in
        ('vwap_intentions_inventory.json','vwap_replay_results.json','full_tick_replay.py','finalize_vwap_replay.py')}
    output['known_limitations']=['Resting causal VWAP target differs from executor market exit at polling time',
        'Tick page cursor moves oldest timestamp minus one millisecond; same-millisecond boundary quotes may be omitted',
        'Historical price touch is not guaranteed broker execution; no queue or actual account tariff',
        'No portfolio capacity, risk manager, swaps, actual shutdowns or forced-close simulation',
        'Executor rules may have changed across the logging period; observed intentions are not a single frozen forward strategy',
        'First intention per pair-day is fixed retrospective deduplication, not all possible order lifecycles',
        'Day-cluster bootstrap conditional on filled days; reused history is not blind out of sample']
    raw_counts=Counter(r['local_wall_time'][:10] for r in inventory['intentions'])
    forced=Counter()
    supervisor=ROOT/'logs'/'vwap_executor_supervisor.log'
    if supervisor.exists():
        for line in supervisor.read_text(encoding='utf-8',errors='replace').splitlines():
            match=re.match(r'\[(\d{4}-\d{2}-\d{2}) ',line)
            if match and 'Heartbeat stale' in line and 'killing hung process' in line:
                forced[match.group(1)]+=1
    dates=[]
    dt=datetime.fromisoformat(min(raw_counts))
    last=datetime.fromisoformat(max(raw_counts))
    while dt<=last:
        if dt.weekday()<5:
            day=dt.date().isoformat()
            selected=[r for r in records if r['day']==day and r['stress']==1]
            stats=statistics(selected)
            dates.append(dict(day=day,raw_log_records=raw_counts[day],unique_intentions=len(selected),
                watchdog_forced_restarts=forced[day],**stats))
        dt+=timedelta(days=1)
    output['days']=dates
    (FOLDER/'vwap_tick_results.json').write_text(json.dumps(output,indent=2,allow_nan=False),encoding='utf-8')
    lines=['# VWAP: відтворення фактичних намірів 25.08–07.10.2026','',
      'Це історичний аналіз, а не звіт про виконані брокером угоди. Реальних ордерів, рестартів, деплою чи змін працюючого бота не було.', '',
      '## Підсумок','',
      f"858 логів; {len(inventory['intentions'])} сирих рядків would enter; {len(orders)} перших унікальних намірів pair-day; {len(hashes)} кешів повних ASK/BID-вікон. UTC+3 перевірено для цього літнього інтервалу.", '',
      '| Модель | Умовні виконання | PF | Середнє R | 95% CI середнього R |',
      '|---|---:|---:|---:|---|']
    stats=output['gross_before_commission']
    ci=stats['day_cluster_mean_ci']
    if ci:
        lines.append(f"| ASK/BID до комісії (спред уже враховано) | {stats['filled']} | {fmt(stats['pf'])} | {fmt(stats['mean_r'])} | {fmt(ci[0])} … {fmt(ci[1])} |")
    for stress,label in [(1,'ASK/BID + 0.02 ATR комісія'),(2,'ASK/BID + 0.04 ATR комісія + 0.02 ATR прослизання')]:
        stats=output['summary']['scenarios'][str(stress)]['all']
        ci=stats['day_cluster_mean_ci']
        lines.append(f"| {label} | {stats['filled']} | {fmt(stats['pf'])} | {fmt(stats['mean_r'])} | {fmt(ci[0])} … {fmt(ci[1])} |")
    lines += ['', 'PF — сума прибутків / сума збитків за абсолютним значенням. Нижче 1 означає, що збитки перевищують прибутки. R — результат відносно записаного ризику LIMIT−SL. Сума R не є доходністю депозиту; кроси корельовані. Витрати умовні, а не перевірений тариф акаунта.', '',
      'Bootstrap: 10000 перевибірок цілих днів із виконаннями, seed 20261009. Історія вже використовувалася: пізній блок не є сліпим OOS.', '',
      '## Ранній і пізній блоки','', '| Витрати | Блок | Виконання | PF | Середнє R |','|---|---|---:|---:|---:|']
    for stress in (1,2):
        for block,label in [('early','25.08–11.09'),('late','14.09–07.10')]:
            s=output['summary']['scenarios'][str(stress)][block]
            lines.append(f"| {stress} | {label} | {s['filled']} | {fmt(s['pf'])} | {fmt(s['mean_r'])} |")
    lines += ['', '## Кожен робочий день','',
      '| Дата | Сирі рядки | Унікальні наміри | Виконання | Не виконано | Невідомо | PF | Сума R | Watchdog-рестарти |',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in dates:
        unfilled=row['statuses'].get('unfilled',0)
        unknown=row['unique_intentions']-row['filled']-unfilled
        lines.append(f"| {row['day']} | {row['raw_log_records']} | {row['unique_intentions']} | {row['filled']} | {unfilled} | {unknown} | {fmt(row['pf'])} | {fmt(row['total_r'])} | {row['watchdog_forced_restarts']} |")
    lines += ['', 'Нуль намірів не доводить справність або зупинку бота. Watchdog-рестарти — лише зареєстровані примусові завершення процесу; це не відсоток uptime і не тривалість простою. Вихідні виключено з торгової таблиці.', '',
      '## Що саме перевірено','',
      '- Виключено входи до часу логу: найраніше timestamp + 1 секунда; тільки ASK≤записаний LIMIT. Повторні polls не нові угоди.',
      '- STOP береться з логу; продаж за BID, stop має пріоритет у неоднозначну мілісекунду. VWAP тільки останнього завершеного M5-бару.',
      '- 16:00 UTC закриття за останнім BID віком не більше 60 секунд; відсутність котирувань позначено невідомою, не нульовим прибутком.',
      '- Масштаб logged LIMIT/SL узгоджується з raw broker prices /100000. Сценарій units_diagnostic у старому M5 JSON відхилено: перемасштабування JPY неправильне.', '',
      '## Обмеження та рішення','']
    limitations_ua=[
        'Вихід моделюється як причинний VWAP-target, а не MARKET після чергового 60-секундного poll живого executor.',
        'Пагінація переходить на найстарішу мілісекунду мінус один; котирування тієї самої мілісекунди на межі сторінок можуть бути пропущені.',
        'Торкання історичного ASK/BID не гарантує виконання брокером; чергу ордерів і фактичний тариф рахунку не враховано.',
        'Не відтворено портфельні ліміти, risk-manager, свопи, фактичні зупинки та примусові закриття.',
        'Правила executor могли змінюватися протягом періоду; це аналіз спостережених намірів, а не єдина незмінна forward-стратегія.',
        'Перший намір на пару/день — зафіксоване ретроспективне правило дедуплікації, не всі можливі життєві цикли ордерів.',
        'Bootstrap умовний на дні з виконаннями; використана раніше історія не є сліпою позавибірковою перевіркою.']
    for limitation in limitations_ua:
        lines.append('- '+limitation)
    s=output['summary']['scenarios']['1']['all']
    unknown=len(orders)-s['filled']-s['statuses'].get('unfilled',0)
    lines += ['',f"Невідомих результатів у базовій моделі: {unknown}. Статуси: {s['statuses']}.", '',
      'Висновок: '+('ця зафіксована модель не показує переваги після витрат; не переносити її на реальні гроші й не підбирати параметри на цих самих даних.' if s['mean_r'] is not None and s['mean_r']<=0 else 'описовий позитивний результат ще не доводить торгової переваги; потрібен незалежний майбутній тест без зміни правил.'), '',
      'Технічні зависання й статистика стратегії — різні задачі. Цей replay не створює пропущених під час простою сигналів. Старе PF 1.42 стосувалося іншої моделі входу, не цього відтворення logged LIMIT/SL.', '',
      'Наступний змістовний крок: окремий незмінний shadow-журнал життєвого циклу (signal → pending → filled/unfilled → exit), який записує ASK/BID та версію правил. Спочатку доказ коректного обліку; не AI-торгівля і не новий перебір параметрів.', '',
      'Відтворення без мережі: `python research_new_methods_20261007/finalize_vwap_replay.py`. Деталі та SHA256 — vwap_tick_results.json; правила — VWAP_TICK_PROTOCOL.md.']
    (FOLDER/'VWAP_FINAL_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(output['summary'],indent=2))

if __name__=='__main__':
    main()
