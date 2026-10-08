"""Bounded nonblocking adapter; disk I/O never runs on the reactor thread."""
import logging
import queue
import threading
import time
from vwap_paper import PaperJournal

logger = logging.getLogger('vwap_paper')

class PaperBridge:
    def __init__(self,path,*,max_positions=5):
        self.path = path
        self.queue = queue.Queue(maxsize=2000)
        self._lost = threading.Event()
        self._stop = threading.Event()
        self.ready = threading.Event()
        self.failed = False
        self._watched = set()
        self._seen = set()
        self._attached = []
        self.thread = threading.Thread(target=self._run,args=(max_positions,),daemon=True,name='vwap-paper-journal')
        self.thread.start()

    def _submit(self,kind,payload):
        if self.failed:
            return False
        try:
            self.queue.put_nowait((kind,payload))
            return True
        except queue.Full:
            self._lost.set()
            return False

    def signal(self,**payload):
        key = (payload['session'],payload['symbol'])
        if key in self._seen:
            return False
        self._watched.add(payload['symbol'])
        submitted = self._submit('signal',payload)
        if submitted:
            self._seen.add(key)
        return submitted

    def target(self,symbol,**payload):
        if symbol in self._watched:
            self._submit('target',dict(symbol=symbol,**payload))

    def quote(self,symbol,**payload):
        if symbol in self._watched:
            self._submit('quote',dict(symbol=symbol,**payload))

    def gap(self):
        self._lost.set()

    def halt(self):
        self._submit('halt',dict(ts=time.time()))

    def attach(self,client,on_spot,is_current=lambda:True):
        if any(c is client for c in self._attached):
            return
        self._attached.append(client)
        client.on('spot_event',lambda event: on_spot(event) if is_current() else None)
        client.on('error',lambda reason: self.gap() if reason=='DISCONNECTED' and is_current() else None)

    def close(self):
        self._stop.set()
        self.thread.join(timeout=2)

    def _run(self,max_positions):
        journal = None
        try:
            journal = PaperJournal(self.path,max_positions=max_positions,restart_ts=time.time())
            self._watched.update(o['symbol'] for o in journal.orders.values() if o['status'] in ('pending','open'))
            self.ready.set()
            logger.info('Paper journal ready: %s',self.path)
            print('Paper journal ready: '+str(self.path),flush=True)
            while not self._stop.is_set():
                if self._lost.is_set():
                    self._lost.clear()
                    # Do not apply an old intention/quote after a known loss.
                    while True:
                        try:
                            kind,payload=self.queue.get_nowait()
                            try:
                                if kind=='signal':
                                    journal.signal(**payload)
                            except (ValueError,TypeError,KeyError):
                                # Loss recovery must tolerate the same malformed
                                # inputs as normal processing, not kill the writer.
                                logger.warning('Paper input rejected during gap recovery')
                            finally:
                                self.queue.task_done()
                        except queue.Empty: break
                    journal.gap(time.time(),'connection_or_queue_gap')
                try:
                    kind,payload = self.queue.get(timeout=.5)
                except queue.Empty:
                    journal.advance(time.time())
                    continue
                try:
                    if time.time()-payload['ts'] > 15 or payload['ts'] > time.time()+1:
                        if kind=='signal':
                            journal.signal(**payload)
                        journal.gap(time.time(),'stale_adapter_event')
                    else:
                        result=getattr(journal,kind)(**payload)
                        if kind=='signal' and result:
                            logger.info('Paper pending: %s %s',payload['session'],payload['symbol'])
                except (ValueError,TypeError,KeyError):
                    journal.gap(time.time(),'invalid_paper_input')
                    logger.warning('Paper input rejected; active outcomes unknown, worker continues')
                finally:
                    self.queue.task_done()
        except Exception:
            self.failed = True
            logger.exception('Paper journal unavailable; no simulated result asserted')
            print('Paper journal unavailable: no simulated result asserted.',flush=True)
        finally:
            self.ready.set()
            if journal is not None:
                journal.close()
