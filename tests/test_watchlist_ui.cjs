const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('webapp/script.js','utf8');
const store = new Map([['zigzag_watchlist', JSON.stringify(['BTCUSD','ETHUSD'])]]);
const context = {
  URLSearchParams, AbortSignal, console,
  localStorage: {getItem:k => store.get(k) || null, setItem:(k,v)=>store.set(k,v)},
  normalizePair:p=>String(p).replaceAll('/','').toUpperCase(),
  buildQuery:()=>'?admin_token=test',
  API_BASE_URL:'', WATCHLIST_STORAGE_KEY:'zigzag_watchlist', watchlistStorageKey:null,
  currentWatchlist:[], allData:{crypto:['BTC/USD','ETH/USD']}, watchlistWritePending:false,
  document:{getElementById:()=>null}, populateLists:()=>{},
  window:{Telegram:true}, tg:{showAlert:()=>{}},
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function loadLocalWatchlist'),source.indexOf('async function loadInitialData')),context);
vm.runInContext(source.slice(source.indexOf('async function toggleFavorite'),source.indexOf('async function fetchSignal')),context);
(async()=>{
  let writes = 0;
  context.fetch=async(_,args)=>{
    writes++; assert.equal(args.method,'POST');
    assert.equal(args.body.get('enabled'),'true');
    return {ok:true,json:async()=>({success:true,watchlist:['BTCUSD','ETHUSD']})};
  };
  const data={user:{user_id:1,is_admin:true},crypto:['BTC/USD','ETH/USD'],watchlist:[]};
  assert.equal((await context.recoverLegacyWatchlist(data)).length,2);
  await context.recoverLegacyWatchlist(data);
  assert.equal(writes,1, 'legacy migration must not resurrect removed pairs');
  assert(store.has('zigzag_watchlist'), 'original legacy cache preserved');
  context.currentWatchlist=['ETHUSD'];
  context.fetch=async()=>({ok:false,json:async()=>({success:false})});
  await context.toggleFavorite({stopPropagation(){}},null,'BTCUSD');
  assert.deepEqual(context.currentWatchlist,['ETHUSD'], 'failure must not add phantom favorite');
  context.fetch=async()=>({ok:true,json:async()=>({success:true,watchlist:['BTCUSD']})});
  await context.toggleFavorite({stopPropagation(){}},null,'BTCUSD');
  assert.deepEqual(context.currentWatchlist,['BTCUSD'], 'use full canonical server result');
  const before = writes;
  await context.recoverLegacyWatchlist({...data,user:{user_id:2,is_admin:false}});
  assert.equal(writes,before, 'ordinary account must not import unscoped cache');
  store.delete('zigzag_watchlist:1:legacy_recovered');
  context.fetch=async()=>({ok:false,json:async()=>({success:false})});
  await assert.rejects(()=>context.recoverLegacyWatchlist(data));
  assert(!store.has('zigzag_watchlist:1:legacy_recovered'), 'failed migration remains retryable');
  context.fetch=async()=>{throw new Error('timeout');};
  context.currentWatchlist=['ETHUSD'];
  await context.toggleFavorite({stopPropagation(){}},null,'ETHUSD');
  assert.deepEqual(context.currentWatchlist,['ETHUSD'], 'failed removal must not hide an active favorite');
  console.log('Watchlist UI: migration, failure, canonical state and account isolation passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
