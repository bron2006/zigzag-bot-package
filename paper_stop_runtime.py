"""Single-process PAPER control experiment; never imports an order executor.

Existing published model signals, ATR stop/1.5R target. This is NOT an
edge-validated strategy. Quotes are received ticks, not guaranteed broker fills.
"""
import json
import logging
import math
import os
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Lock
import time

from paper_stop_journal import PaperStopJournal
from strategy_mode import paper_entries_enabled

logger = logging.getLogger(__name__)
PAIRS = ('EURUSD','GBPUSD','AUDUSD','NZDUSD','BTCUSD','ETHUSD')
_quotes = Queue(maxsize=50000)
_intents = Queue(maxsize=512)
_lock = Lock()
_overflow = False
_initialized = False
_terms = {}
_metadata_client = None
_metadata_pending = False
_metadata_next = 0
_started = time.time()
_last_cycle = None
_last_error = None


def enabled():
    return bool(os.getenv('PAPER_STOP_JOURNAL_PATH'))


def receive(pair, quote):
    """O(1) SDK callback: no disk/network on the reactor thread."""
    global _overflow
    if not enabled() or pair not in PAIRS:
        return
    try:
        _quotes.put_nowait((pair, dict(quote)))
    except Full:
        _overflow = True  # never silently drop a possible stop touch


def connection_gap():
    if enabled():
        try:
            _quotes.put_nowait((None,None))
        except Full:
            global _overflow
            _overflow = True


def submit(result):
    """Called ONLY after a confirmed persisted publication receipt."""
    if not enabled() or not paper_entries_enabled():
        return
    try:
        _intents.put_nowait(dict(result))
    except Full:
        logger.error('PAPER intent queue full; no position entered')


def refresh_metadata(state, reactor):
    """Read-only symbol/asset requests through the existing SDK queue."""
    global _metadata_client, _metadata_pending, _metadata_next, _terms
    client=state.client
    now=time.time()
    if client is not _metadata_client:
        _metadata_client=client
        _terms={}
        _metadata_pending=False
        _metadata_next=0
    account_id=getattr(getattr(client,'_client',None),'account_id',None)
    if not enabled() or not client or not account_id or not state.SYMBOLS_LOADED or _metadata_pending or now<_metadata_next:
        return
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAAssetListReq,ProtoOAAssetListRes,ProtoOASymbolByIdReq,ProtoOASymbolByIdRes)
    lights={pair:state.get_symbol_details(pair) for pair in PAIRS}
    ids=[s.symbolId for s in lights.values() if s is not None]
    if not ids:
        return
    _metadata_pending=True
    _metadata_next=now+30
    d=client.send(ProtoOAAssetListReq(ctidTraderAccountId=account_id))
    d.addTimeout(10,reactor)
    def assets(message):
        if client is not state.client or client is not _metadata_client:
            return
        result=ProtoOAAssetListRes()
        result.ParseFromString(message.payload)
        usd={asset.assetId for asset in result.asset if asset.name=='USD'}
        request=ProtoOASymbolByIdReq(ctidTraderAccountId=account_id,symbolId=ids)
        child=client.send(request)
        child.addTimeout(10,reactor)
        def symbols(message):
            global _terms, _metadata_next
            if client is not state.client or client is not _metadata_client:
                return
            result=ProtoOASymbolByIdRes()
            result.ParseFromString(message.payload)
            details={symbol.symbolId:symbol for symbol in result.symbol}
            terms={}
            for pair,light in lights.items():
                if light is None or light.quoteAssetId not in usd:
                    continue
                symbol=details.get(light.symbolId)
                if symbol is None:
                    continue
                values=[getattr(symbol,k,0)/100 for k in ('minVolume','stepVolume','maxVolume')]
                if not all(v>0 and math.isfinite(v) for v in values):
                    continue
                if getattr(symbol,'tradingMode',0)!=0:  # ENABLED in SDK enum
                    continue
                terms[pair]=dict(minimum=values[0],step=values[1],maximum=values[2],quote_currency='USD')
            _terms=terms
            _metadata_next=time.time()+300
            logger.info('PAPER broker USD specs verified: %s',','.join(sorted(terms)))
        return child.addCallback(symbols)
    def finished(value):
        global _metadata_pending
        if client is _metadata_client:
            _metadata_pending=False
        return value
    def failed(failure):
        global _terms
        if client is _metadata_client:
            _terms={}
        logger.warning('PAPER specs unavailable; entries blocked: %s',failure.getErrorMessage())
        return None
    d.addCallback(assets)
    d.addBoth(finished)
    d.addErrback(failed)


def health():
    return dict(enabled=enabled(),heartbeat=_last_cycle,error=_last_error,
                status=('running' if paper_entries_enabled() else 'paused_no_strategy') if _last_cycle and time.time()-_last_cycle<10 and not _last_error else 'not_ready',
                accepting_entries=paper_entries_enabled(),
                eligible_pairs=sorted(_terms),strategy='existing_signals_control_atr_stop_v1',
                risk_fraction=.005,max_positions=1,target_R=1.5,max_holding_minutes=30,
                costs='spread_plus_assumed_reserve_not_verified_broker_fees',
                fee_assumptions='FX $7/100000 units round trip; crypto 0.10% entry notional round trip',
                real_orders=False)


def cycle(state, now=None, *, require_mount=True):
    """Dedicated non-overlapping worker cycle. No network while SQLite is open."""
    global _initialized, _overflow, _last_cycle, _last_error
    if not enabled() or not _lock.acquire(blocking=False):
        return
    now=time.time() if now is None else now
    book=None
    try:
        path=Path(os.environ['PAPER_STOP_JOURNAL_PATH'])
        if require_mount and (path.parent!=Path('/data') or not os.path.ismount('/data')):
            raise RuntimeError('paper_requires_persistent_data_mount')
        book=PaperStopJournal(str(path))
        if not _initialized:
            book.mark_gap()  # no invented target/stop history across a restart
            _initialized=True
        if _overflow:
            book.mark_gap()
            _overflow=False
        active=book.active()
        processed=0
        while processed<50000:
            try:
                pair,quote=_quotes.get_nowait()
            except Empty:
                break
            processed+=1
            if pair is None:
                book.mark_gap()
                active=book.active()
                continue
            if not active or pair!=active['pair'] or active['reason']=='path_gap':
                continue
            key='bid_ts' if active['side']==1 else 'ask_ts'
            previous=json.loads(active['last_quote'])
            price_key='bid' if active['side']==1 else 'ask'
            if quote[key]<previous[key] or (quote[key]==previous[key] and quote[price_key]==previous[price_key]):
                continue
            if now-quote[key]>5 or quote[key]-previous[key]>30:
                book.mark_gap()
                active=book.active()
                continue
            entered=json.loads(active['entry_quote'])
            expiry=quote[key]-entered.get('executed_ts',entered['ts'])>=1800
            result=book.observe(pair,quote,now,force_reason='time_exit' if expiry else None)
            if result['status']=='closed':
                logger.info('PAPER closed %s: %s',pair,json.dumps(result,sort_keys=True))
            active=book.active()
        while True:
            try:
                signal=_intents.get_nowait()
            except Empty:
                break
            pair=str(signal.get('pair','')).replace('/','').upper()
            intent=str(signal.get('signal_outcome_id',''))
            ts=signal.get('ts')
            if not intent or not isinstance(ts,(int,float)) or not math.isfinite(ts):
                continue
            if book.connection.execute('SELECT 1 FROM events WHERE intent=?',(intent,)).fetchone():
                continue
            reason=None
            terms=dict(_terms.get(pair,{}))
            quote=state.get_paper_quote(pair,now)
            side={'BUY':1,'SELL':-1}.get(signal.get('verdict_text'))
            atr=signal.get('atr')
            today=now-now%86400
            pnl=sum(float(row[0]) for row in book.connection.execute(
                "SELECT pnl FROM positions WHERE state='closed' AND json_extract(last_quote,'$.ts')>=?",(today,)))
            cash=float(book.connection.execute('SELECT balance FROM account WHERE id=1').fetchone()[0])
            if not paper_entries_enabled(): reason='strategy_entries_disabled'
            elif pair not in PAIRS: reason='non_USD_or_not_in_control_universe'
            elif not 0<=now-ts<=10: reason='expired_signal_no_late_entry'
            elif not terms: reason='broker_specs_unavailable'
            elif active: reason='one_open_position' if active['reason']!='path_gap' else 'path_gap_review_required'
            elif pnl<=-(cash-pnl)*.02: reason='daily_loss_limit'
            elif not quote: reason='no_fresh_entry_quote'
            elif not side or not isinstance(atr,(int,float)) or not math.isfinite(atr) or atr<=0: reason='invalid_ATR_or_side'
            elif atr<3*(quote['ask']-quote['bid']): reason='spread_too_large_for_stop'
            elif 20<= (now%86400)/3600 <22.5: reason='rollover_entry_block'
            if reason:
                book.event(intent,pair,ts,'skipped',reason)
                continue
            entry=quote['ask'] if side==1 else quote['bid']
            fee=.00007 if pair not in ('BTCUSD','ETHUSD') else entry*.001
            quote=dict(quote,source='cTrader',signal_id=intent,signal_ts=ts,atr=atr,
                       experiment='existing_signals_control_atr_stop_v1',
                       costs='spread_plus_assumed_reserve',max_holding_seconds=1800)
            result=book.open(intent,pair,side,quote,now,entry-side*atr,entry+side*1.5*atr,
                             fee_per_unit=fee,**terms)
            book.event(intent,pair,ts,result['status'],result.get('reason'))
            active=book.active()
            logger.info('PAPER intent %s %s: %s',intent,pair,json.dumps(result,sort_keys=True))
        _last_cycle=now
        _last_error=None
        payload=health()
        if active and active['reason']=='path_gap':
            payload['status']='suspended_path_gap'
        book.heartbeat(payload)
    except Exception:
        _last_error='paper_worker_error'
        if book:
            try:
                book.mark_gap()
            except Exception:
                pass
        logger.exception('PAPER cycle failed; no fabricated trades or cash reset')
    finally:
        if book:
            book.close()
        _lock.release()
