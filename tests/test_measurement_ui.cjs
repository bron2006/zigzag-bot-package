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
console.log('UI: 8 assertions passed');
