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
context.renderWinrateStats({ok:true,scope:'current_test',measurement_audit:audit},null);
assert(context.winrateModalBody.innerHTML.includes('NEWPAIR'), 'history failure does not hide current test');
console.log('UI: current experiment, collapsed history, escaping and missing data passed');
