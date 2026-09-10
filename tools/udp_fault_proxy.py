#!/usr/bin/env python3
"""Deterministic single-client UDP relay for course-network validation."""
from dataclasses import dataclass,asdict
import argparse,heapq,json,select,socket,threading,time


@dataclass(frozen=True)
class Faults:
    delay_ms:int=0
    drop_every:int=0
    cut:bool=False
    def __post_init__(self):
        if type(self.delay_ms) is not int or not 0<=self.delay_ms<=2000:raise ValueError('delay_ms must be 0..2000')
        if type(self.drop_every) is not int or not 0<=self.drop_every<=10000:raise ValueError('drop_every must be 0..10000')
        if type(self.cut) is not bool:raise ValueError('cut must be bool')


class UdpFaultProxy:
    def __init__(self,upstream,*,listen=('127.0.0.1',0),faults=None):
        self.down=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.down.bind(listen);self.down.setblocking(False)
        self.up=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.up.connect(upstream);self.up.setblocking(False)
        self.address=self.down.getsockname();self._faults=faults or Faults();self._lock=threading.Lock()
        self._stop=threading.Event();self._thread=None;self._client=None;self._queue=[];self._seq=0
        self.metrics={'received':0,'forwarded':0,'dropped':0,'client_packets':0,'server_packets':0}
    def set_faults(self,faults):
        if not isinstance(faults,Faults):raise ValueError('faults must be Faults')
        with self._lock:self._faults=faults
    def start(self):
        if self._thread:raise RuntimeError('proxy already started')
        self._thread=threading.Thread(target=self._run,name='UDP fault proxy',daemon=True);self._thread.start();return self
    def _schedule(self,sock,data,address):
        with self._lock:
            faults=self._faults;self._seq+=1;seq=self._seq;self.metrics['received']+=1
            if faults.cut or (faults.drop_every and seq%faults.drop_every==0):self.metrics['dropped']+=1;return
            heapq.heappush(self._queue,(time.monotonic()+faults.delay_ms/1000,seq,sock,data,address))
    def _run(self):
        while not self._stop.is_set():
            ready,_,_=select.select([self.down,self.up],[],[],.01)
            for sock in ready:
                try:data,address=sock.recvfrom(65535)
                except (BlockingIOError,ConnectionRefusedError):continue
                except OSError:
                    if self._stop.is_set():return
                    continue
                if sock is self.down:
                    self._client=address;self.metrics['client_packets']+=1;self._schedule(self.up,data,None)
                elif self._client:
                    self.metrics['server_packets']+=1;self._schedule(self.down,data,self._client)
            now=time.monotonic()
            while self._queue and self._queue[0][0]<=now:
                _,_,sock,data,address=heapq.heappop(self._queue)
                try:sock.send(data) if address is None else sock.sendto(data,address);self.metrics['forwarded']+=1
                except OSError:pass
    def close(self):
        self._stop.set()
        if self._thread:self._thread.join(2)
        self.down.close();self.up.close()
    def __enter__(self):return self.start()
    def __exit__(self,*args):self.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('host');p.add_argument('port',type=int);p.add_argument('--listen-port',type=int,default=0);p.add_argument('--delay-ms',type=int,default=0);p.add_argument('--drop-every',type=int,default=0);a=p.parse_args()
    proxy=UdpFaultProxy((a.host,a.port),listen=('127.0.0.1',a.listen_port),faults=Faults(a.delay_ms,a.drop_every)).start()
    print(json.dumps({'listen':proxy.address,'faults':asdict(proxy._faults)}),flush=True)
    try:
        while True:time.sleep(1)
    except KeyboardInterrupt:pass
    finally:proxy.close();print(json.dumps(proxy.metrics))
