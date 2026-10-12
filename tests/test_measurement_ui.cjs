const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('webapp/script.js', 'utf8');
const start = source.indexOf('function winrateRateClass');
const end = source.indexOf('// Single source of truth', start);
const context = {winrateModalBody: {innerHTML: ''},
    escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    tr: key => key};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
assert.equal(context.winrateRateClass(90), 'neutral');
const pairs = Array.from({length: 16}, (_, i) => ({pair: `PAIR${i}`, resolved: 5, wins: 1, losses: 1, unknown: 3}));
const html = context.renderWinrateByPair({by_pair: pairs});
assert(html.includes('PAIR15'));
assert(html.includes('визначено: 2'));
assert(html.includes('невідомо: 3'));
context.renderWinrateStats({ok:false}, {ok:true});
assert(context.winrateModalBody.innerHTML.includes('це не нуль сигналів'));
const audit = {legacy_total: 100, missing_reasons: {no_valid_quote_in_5s_window: 1},
    recent: [{id:1, pair:'<script>', direction:'BUY', entry_ts:'2026-10-10', entry:100, status:'unknown'}],
    scenario: {measured_balance:998, measured_pnl:-2, complete:false, balance_lower:988, balance_upper:1006}};
const report = context.renderMeasurementAudit(audit);
assert(report.includes('НЕПОВНИЙ'));
assert(report.includes('$988–$1006'));
assert(report.includes('&lt;script&gt;'));
assert(!report.includes('<script>'));
audit.total = 2;
audit.counts = {win:1, pending:1};
audit.asof_comparison = {counts: {checked:2, available:1, original_unknown_with_price:1}};
audit.by_pair = [{pair:'NEWPAIR',total:2,counts:{win:1,pending:1},win_rate:100}];
context.renderWinrateStats({ok:true,scope:'current_test',measurement_audit:audit},
    {ok:true,total:999,wins:888,by_pair:[{pair:'OLDPAIR',total:999,wins:888}]});
const currentHtml = context.winrateModalBody.innerHTML;
const detailsStart = currentHtml.indexOf('<details');
assert(detailsStart > 0);
assert(currentHtml.slice(0,detailsStart).includes('Поточний тест від 10.10.2026'));
assert(currentHtml.slice(0,detailsStart).includes('NEWPAIR'));
assert(!currentHtml.slice(0,detailsStart).includes('OLDPAIR'));
assert(!currentHtml.slice(0,detailsStart).includes('999'));
assert(!currentHtml.includes('<details open'), 'history must be collapsed by default');
const main = currentHtml.slice(0, detailsStart);
assert(main.indexOf('Умовний баланс') < main.indexOf('NEWPAIR'), 'balance above pairs');
assert(main.includes('$998.00'));
assert(main.includes('без даних'));
assert(!main.includes('Останні 50'));
assert(!main.includes('Діагностика'));
assert(!main.includes('Перший запис'));
assert(!main.includes('Перевірка ціни на завершенні'));
assert(currentHtml.includes('Перевірка ціни на завершенні: 1 із 2'));
assert(currentHtml.includes('Окреме порівняння, баланс не змінює'));
assert(currentHtml.includes('<summary>Деталі тесту</summary>'));
context.renderWinrateStats({ok:true,scope:'current_test',measurement_audit:audit,
    measurement_runtime:{since:'now',counters:{}}},null);
const withRuntime = context.winrateModalBody.innerHTML;
assert(withRuntime.indexOf('Діагностика') > withRuntime.indexOf('<summary>Деталі тесту</summary>'));
assert(withRuntime.indexOf('Діагностика') < withRuntime.indexOf('</details>'));
context.renderWinrateStats({ok:true,scope:'current_test',measurement_audit:audit},null);
assert(context.winrateModalBody.innerHTML.includes('NEWPAIR'), 'history failure does not hide current test');
audit.valuation='asof60';
context.renderWinrateStats({ok:true,scope:'current_test',measurement_audit:audit,
    original_measurement_audit:{...audit,valuation:'strict'}},null);
const selected=context.winrateModalBody.innerHTML;
assert(selected.includes('Ціна на завершенні · вік сторін до 60 с'));
assert(selected.includes('Попередній спосіб: нова котировка після завершення'));
assert(!selected.includes('<details open'));
assert(selected.includes('$998.00'));
console.log('UI: current experiment, collapsed history, escaping and missing data passed');

context.renderTradingDashboard({ok:true,status:'not_started',planned_initial:1000,open_positions:[],closed_positions:[]},
    {ok:true,measurement_audit:audit},null);
assert(context.winrateModalBody.innerHTML.includes('Ще не запущено'));
assert(!context.winrateModalBody.innerHTML.includes('Попередній тест'));
context.renderTradingDashboard({ok:true,status:'account_available',balance:1000,equity:995,unrealized:-5,
    open_positions:[{pair:'<script>',side:1,entry:100,stop:98,target:103,units:2,current:99,pnl:-5}],
    closed_positions:[{pair:'CLOSED',side:-1,exit:97,pnl:6,reason:'target'}]},null,null);
let dashboard=context.winrateModalBody.innerHTML;
assert(dashboard.indexOf('Баланс')<dashboard.indexOf('Пари'));
assert(dashboard.includes('вхід 100 · стоп 98 · тейк 103'));
assert(dashboard.includes('&lt;script&gt;'));
assert(!dashboard.includes('<script>'));
assert(dashboard.includes('CLOSED'));
assert(!dashboard.includes('Закриті угоди'));
assert(!dashboard.includes('Відкриті угоди'));
context.renderTradingDashboard({ok:false},null,null);
assert(context.winrateModalBody.innerHTML.includes('це не нульовий баланс'));
const forward={enabled:true,status:'collecting',candles_fresh:true,pairs:['EURUSD','GBPUSD'],
    rules:['channel24','failed24','compression','ny_h4_close_reclaim_v1'],
    ny_h4_states:[{pair:'EURUSD',status:'waiting_return',low:1.1,high:1.2},{pair:'GBPUSD',status:'setup_before_activation',low:1.3,high:1.4}],
    sources:[{pair:'EURUSD',last_bar:1000,error:null},{pair:'GBPUSD',last_bar:1000,error:null}],counts:[],recent:[]};
context.renderTradingDashboard({ok:true,status:'account_available',balance:999.37,
    runtime:{status:'paused_no_strategy'},open_positions:[],closed_positions:[{pair:'GBPUSD',side:-1,pnl:-.63,reason:'stop'}],
    by_pair:[{pair:'GBPUSD',opened:0,closed:1,pnl:-.63}],forward_research:forward},
    {ok:true,measurement_audit:audit},null);
dashboard=context.winrateModalBody.innerHTML;
assert(dashboard.includes('$999.37'));
assert(dashboard.indexOf('Баланс')<dashboard.indexOf('Пари'));
assert.equal((dashboard.match(/GBPUSD/g)||[]).length,1,'each pair occurs only once, without duplicate trade sections');
assert(dashboard.includes('$-0.63'));
assert(dashboard.includes('Чекаємо повернення'));
assert(dashboard.includes('1.1 — 1.2'));
assert(dashboard.includes('00–04 Нью-Йорк'));
assert(!dashboard.includes('<details'));
assert(!dashboard.includes('Попередній тест'));
assert(!dashboard.includes('Витрати'));
assert(!dashboard.includes('Пробій діапазону'));
assert(!dashboard.includes('Умови тесту'));
assert(!dashboard.includes('Оновити рахунок'));
console.log('Compact dashboard: one balance, one row per pair, NY status, no old archive or duplicate trade sections passed');

(async()=>{
    let hidden=true, poll, cleared=false;
    const calls=[];
    const pollingContext={winrateModalBody:{innerHTML:''},
        winrateModal:{classList:{remove:()=>hidden=false,add:()=>hidden=true,contains:()=>hidden}},
        setInterval:(callback)=>{poll=callback;return 1;},clearInterval:()=>cleared=true,
        apiGet:async(path)=>{calls.push(path);return {ok:true};},
        renderTradingDashboard:()=>{},escapeHtml:context.escapeHtml,tr:context.tr,console};
    vm.createContext(pollingContext);
    vm.runInContext(source.slice(source.indexOf('let paperRefreshTimer'),source.indexOf('function winrateRateClass')),pollingContext);
    pollingContext.openWinrateModal();
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(calls.length,1);
    await poll();
    assert.equal(calls.length,2);
    assert.equal(calls.at(-1),'/api/stats/paper_stops','auto-refresh must not repeatedly query the old DB reports');
    pollingContext.closeWinrateModal();
    assert(cleared);
    await poll();
    assert.equal(calls.length,2,'closed dashboard must not keep polling');
    console.log('Paper dashboard: bounded live refresh and close cleanup passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
