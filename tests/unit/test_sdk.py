import json,os,socket,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game,ActionError,ConnectionError,ProtocolError,Snapshot
from luanti_course.client import profile_path,find_binary

def snapshot(**overrides):
    value=dict(position=[0,1,2],eye=[0,2.6,2],yaw=0,pitch=0,hp=20,dead=False,control='observe',control_epoch=1,frame=10,inventory_revision=2,inventory={'main':{'width':9,'items':[{'name':'test:wood','count':3,'wear':0},{'name':'','count':0,'wear':0}]}},form={'id':0,'lists':[]})
    value.update(overrides);return value

class SDKTests(unittest.TestCase):
    def game(self,handler):
        a,b=socket.socketpair();game=Game(a,Path('/unused/session.json'),timeout=.5)
        self.addCleanup(game.close);self.addCleanup(b.close)
        def serve():
            pending=b''
            try:
                while True:
                    chunk=b.recv(65536)
                    if not chunk:return
                    pending+=chunk
                    while b'\n' in pending:
                        line,pending=pending.split(b'\n',1);q=json.loads(line)
                        answer=handler(q)
                        if answer is None:b.close();return
                        if isinstance(answer,bytes):b.sendall(answer)
                        else:b.sendall((json.dumps(answer)+'\n').encode())
            except OSError:pass
        t=threading.Thread(target=serve,daemon=True);t.start();return game
    def test_snapshot_helpers(self):
        s=Snapshot.from_dict(snapshot());self.assertEqual(s.position,(0,1,2));self.assertEqual(s.inventory['main'].count('test:wood'),3);self.assertEqual(s.inventory['main'].find('test:wood'),0);self.assertEqual(s.inventory['main'].empty_slot(),1)
    def test_observe_is_read_only(self):
        received=[]
        def reply(q):received.append(q);return dict(snapshot(),id=q['id'],status='snapshot')
        g=self.game(reply);self.assertEqual(g.observe().control,'observe');self.assertEqual(received[0]['op'],'observe');self.assertNotIn('control_epoch',received[0])
    def test_explicit_control(self):
        def reply(q):
            if q['op']=='observe':return dict(snapshot(),id=q['id'],status='snapshot')
            return dict(id=q['id'],frame=10,status='submitted',control_epoch=1)
        g=self.game(reply);g.take_control();self.assertEqual(g._epoch,1);g.release_control();self.assertIsNone(g._epoch)
    def test_action_error_no_retry(self):
        received=[]
        def reply(q):received.append(q);return dict(id=q['id'],status='error',error='control_released')
        g=self.game(reply)
        with self.assertRaises(ActionError):g.wield(0)
        self.assertEqual(len(received),1);self.assertIsNone(g._epoch)
    def test_wrong_response_id_closes_connection(self):
        g=self.game(lambda q:dict(id=999,status='submitted'))
        with self.assertRaises(ProtocolError):g.wield(0)
        self.assertTrue(g._closed)
    def test_malformed_response(self):
        g=self.game(lambda q:b'not json\n')
        with self.assertRaises(ProtocolError):g.observe()
        self.assertTrue(g._closed)
    def test_eof_is_connection_error(self):
        g=self.game(lambda q:None)
        with self.assertRaises(ConnectionError):g.observe()
    def test_oversized_response_closes_connection(self):
        g=self.game(lambda q:b'x'*(513*1024))
        with self.assertRaises(ProtocolError):g.observe()
    def test_close_tolerates_game_already_exited(self):
        g=self.game(lambda q:None);g._epoch=1
        g.close()
        self.assertTrue(g._closed)
    def test_manual_owner_error_clears_agent_epoch(self):
        g=self.game(lambda q:dict(id=q['id'],status='error',error='manual_control_active'));g._epoch=1
        with self.assertRaisesRegex(ActionError, 'human is playing'):g._request('acquire')
        self.assertIsNone(g._epoch)
    def test_no_retry_after_transport_failure(self):
        g=self.game(lambda q:None)
        with self.assertRaises(ConnectionError):g.wield(1)
        with self.assertRaises(ConnectionError):g.wield(1)
    def test_invalid_radius_rejected_before_transport(self):
        g=self.game(lambda q:None)
        for radius in [-1,7,True,1.5]:
            with self.assertRaises(ValueError):g.observe(radius)
    def test_invalid_orientation(self):
        g=self.game(lambda q:None)
        for angles in [(float('nan'),0),(0,float('inf')),(36001,0),(0,90),(True,0)]:
            with self.assertRaises(ValueError):g.look(*angles)
    def test_invalid_controls(self):
        g=self.game(lambda q:None)
        with self.assertRaises(ValueError):g.move('teleport')
        for keys,seconds in [([],1),(['unknown'],1),(['forward'],0),(['forward'],61),(['forward'],float('nan'))]:
            with self.assertRaises(ValueError):g.hold(keys,seconds)
    def test_hold_finally_stops(self):
        g=self.game(lambda q:None);ops=[]
        def submit(op,**kwargs):
            ops.append(op)
            if op=='input':raise ActionError('control_released')
        with patch.object(g,'_submit',submit):
            with self.assertRaises(ActionError):g.move(seconds=.05)
        self.assertEqual(ops,['input','stop']);self.assertFalse(g._action_lock.locked())
    def test_submission_does_not_claim_completion(self):
        g=self.game(lambda q:dict(id=q['id'],frame=10,status='submitted'))
        receipt=g.craft_grid();self.assertEqual(receipt.status,'submitted');self.assertEqual(receipt.operation,'craft');self.assertFalse(hasattr(receipt,'success'))
    def test_explicit_profile(self):
        with patch.dict(os.environ,{'LUANTI_USER_PATH':'/tmp/course-explicit'}):self.assertEqual(profile_path(),Path('/tmp/course-explicit'))
    def test_missing_client_is_actionable(self):
        with self.assertRaisesRegex(ConnectionError,'does not exist'):find_binary('/does/not/exist/luanti')
    def test_missing_session_is_actionable(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ConnectionError,'join a world first'):Game.connect(profile=d)
    def test_endpoint_host_is_loopback_only(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'course-control-1.json';f.write_text(json.dumps(dict(host='example.com',port=3000,protocol=1,token='0'*64)))
            with patch('socket.create_connection') as dial:
                with self.assertRaises(ConnectionError):Game.connect(profile=d)
                dial.assert_not_called()
    def test_cli_help(self):
        from luanti_course.cli import main
        with self.assertRaises(SystemExit) as result:main(['--help'])
        self.assertEqual(result.exception.code,0)

if __name__=='__main__':unittest.main()
