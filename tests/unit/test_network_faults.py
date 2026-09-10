import socket,sys,threading,time,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from udp_fault_proxy import Faults,UdpFaultProxy

class Echo:
    def __enter__(self):
        self.stop=threading.Event();self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.sock.bind(('127.0.0.1',0));self.sock.settimeout(.05)
        def run():
            while not self.stop.is_set():
                try:data,peer=self.sock.recvfrom(1000);self.sock.sendto(data,peer)
                except socket.timeout:pass
                except OSError:break
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start();return self
    def __exit__(self,*a):self.stop.set();self.sock.close();self.thread.join(1)

class FaultTests(unittest.TestCase):
    def test_delay_loss_cut_and_resume_on_real_udp(self):
        with Echo() as echo,UdpFaultProxy(echo.sock.getsockname()) as proxy:
            client=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);client.settimeout(.4)
            started=time.monotonic();client.sendto(b'a',proxy.address);self.assertEqual(client.recv(10),b'a');self.assertLess(time.monotonic()-started,.25)
            proxy.set_faults(Faults(delay_ms=70));started=time.monotonic();client.sendto(b'b',proxy.address);self.assertEqual(client.recv(10),b'b');self.assertGreaterEqual(time.monotonic()-started,.12)
            proxy.set_faults(Faults(cut=True));client.sendto(b'c',proxy.address)
            with self.assertRaises(socket.timeout):client.recv(10)
            proxy.set_faults(Faults());client.sendto(b'd',proxy.address);self.assertEqual(client.recv(10),b'd')
            self.assertGreaterEqual(proxy.metrics['dropped'],1);client.close()

    def test_invalid_faults_are_rejected(self):
        for args in ((-1,0,False),(0,-1,False),(0,0,1)):
            with self.assertRaises(ValueError):Faults(*args)

if __name__=='__main__':unittest.main()
