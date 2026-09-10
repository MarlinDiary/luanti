import importlib.util,json,sys,time,unittest,subprocess,tempfile
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('remote_audit',ROOT/'tests/integration/remote_survival_audit.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
class AuditLifecycleTests(unittest.TestCase):
 def child(self):return subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 def check_shutdown(self,**kw):
  child=self.child();watch=audit.OwnedClientWatchdog(child,**kw).start();self.addCleanup(watch.close);return child,watch
 def wait_end(self,child):child.wait(timeout=3);self.assertIsNotNone(child.returncode)
 def test_deadline_ends_owned_process_even_without_sdk(self):
  child,watch=self.check_shutdown(seconds=.15);self.wait_end(child);self.assertEqual(watch.reason,'session_deadline')
 def test_join_timeout_is_independent_of_sdk(self):
  child,watch=self.check_shutdown(join_seconds=.15);self.wait_end(child);self.assertEqual(watch.reason,'join_timeout')
 def test_stalled_observer_ends_native_client(self):
  child,watch=self.check_shutdown(stale_seconds=.15);watch.sample({'hp':20});self.wait_end(child);self.assertEqual(watch.reason,'observation_stalled')
 def test_health_floor_ends_native_client_before_more_steps(self):
  child,watch=self.check_shutdown();watch.sample({'hp':11});self.wait_end(child);self.assertEqual(watch.reason,'health_floor')
 def test_death_and_manual_takeover_end_run(self):
  for sample,reason in [({'dead':True},'player_dead'),({'control':'manual'},'manual_takeover')]:
   child,watch=self.check_shutdown();watch.sample(sample);self.wait_end(child);self.assertEqual(watch.reason,reason)
 def test_normal_completion_closes_owned_process(self):
  child,watch=self.check_shutdown();watch.close();self.assertIsNone(watch.reason);self.assertIsNotNone(child.poll())
 def test_failed_step_is_not_replayed(self):
  calls=[];g=NS(observe=lambda r:NS(dead=False,control='agent'),flee_from=lambda **kw:NS(ok=False,to_dict=lambda:{'status':'blocked'}),collect=lambda **kw:calls.append(kw));rows=[]
  status=audit.execute_plan(g,[{'action':'flee_from'},{'action':'collect','item':'tree'}],rows.append,lambda:15)
  self.assertEqual(status,'step_failed');self.assertEqual(calls,[]);self.assertEqual(len(rows),1)
 def test_plan_rejects_respawn_chat_unknown_and_nonfinite_time(self):
  for plan in [[{'action':'respawn'}],[{'action':'chat'}],[{'action':'flee_from','cheat':True}],[{'action':'observe','timeout':float('nan')}]]:
   with self.assertRaises(ValueError):audit.validate_plan(plan)
 def test_dead_initial_state_executes_no_step(self):
  g=NS(observe=lambda r:NS(dead=True,control='observe'),flee_from=lambda **kw:self.fail('movement'))
  self.assertEqual(audit.execute_plan(g,[{'action':'flee_from'}],lambda r:None,lambda:10),'control_lost')
 def test_collect_plan_matches_real_sdk_parameter_name(self):
  calls=[]
  def collect(resource,count=1,*,timeout):
   calls.append((resource,count,timeout));return NS(ok=True,to_dict=lambda:{'status':'success'})
  g=NS(observe=lambda r:NS(dead=False,control='agent'),collect=collect)
  self.assertEqual(audit.execute_plan(g,[{'action':'collect','item':'mcl_core:tree','count':2,'timeout':10}],lambda r:None,lambda:20),'complete')
  self.assertEqual(calls,[('mcl_core:tree',2,10)])
 def test_macos_child_environment_reconstructs_background_libraries(self):
  import tempfile,os
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);a=root/'cursor.dylib';b=root/'focus.dylib';a.touch();b.touch()
   with patch.object(audit.sys,'platform','darwin'),patch.dict(os.environ,{'COURSE_TEST_DYLD_LIBRARIES':str(a)+':'+str(b)},clear=True):
    env=audit.launch_environment(root,root)
   self.assertEqual(env['DYLD_INSERT_LIBRARIES'],str(a)+':'+str(b));self.assertNotIn('COURSE_TEST_DYLD_LIBRARIES',env)
   self.assertEqual(env['COURSE_FOCUS_AUDIT_LOG'],str((root/'focus.txt').resolve()))
 def test_missing_background_libraries_fail_before_native_launch(self):
  import os
  from unittest.mock import patch
  with patch.object(audit.sys,'platform','darwin'),patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):audit.launch_environment(Path('/tmp'),Path('/tmp'))
if __name__=='__main__':unittest.main()

class BackgroundAuditTests(unittest.TestCase):
 def test_focus_and_audio_end_owned_process(self):
  child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'])
  watch=audit.OwnedClientWatchdog(child).start()
  try:
   watch.sample({'focused':True});self.assertIsNone(watch.reason)
   watch.sample({'audio_enabled':True});child.wait(timeout=3);self.assertEqual(watch.reason,'unexpected_audio')
  finally:watch.close()
 def test_actual_frontmost_pid_ends_owned_process(self):
  with tempfile.TemporaryDirectory() as folder:
   child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)']);log=Path(folder)/'frontmost.jsonl'
   watch=audit.OwnedClientWatchdog(child,focus_log=log).start()
   try:
    log.write_text(json.dumps({'pid':child.pid})+'\n');child.wait(timeout=3)
    self.assertEqual(watch.reason,'unexpected_frontmost')
   finally:watch.close()
 def test_only_one_audit_and_release_on_exception(self):
  with self.assertRaisesRegex(ValueError,'test cleanup'):
   with audit.ExclusiveRemoteAudit():
    with self.assertRaises(RuntimeError):
     with audit.ExclusiveRemoteAudit():pass
    raise ValueError('test cleanup')
  with audit.ExclusiveRemoteAudit():pass
 def test_child_sets_background_switches(self):
  from unittest.mock import patch
  import os,tempfile
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);a=root/'a';b=root/'b';a.touch();b.touch()
   with patch.object(audit.sys,'platform','darwin'),patch.dict(os.environ,{'COURSE_TEST_DYLD_LIBRARIES':str(a)+':'+str(b)},clear=True):env=audit.launch_environment(root,root)
   for key in ('LUANTI_COURSE_TEST_SILENT','COURSE_TEST_BACKGROUND','SDL_MAC_BACKGROUND_APP','SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN'):self.assertEqual(env[key],'1')

class AccessoryBundleTests(unittest.TestCase):
 def test_macos_background_bundle_required(self):
  import tempfile,plistlib
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);binary=root/'Example.app/Contents/MacOS/luanti';binary.parent.mkdir(parents=True);binary.touch();info=binary.parents[1]/'Info.plist'
   with patch.object(audit.sys,'platform','darwin'):
    for v in ({},{'LSUIElement':False}):
     info.write_bytes(plistlib.dumps(v))
     with self.assertRaises(ValueError):audit.validate_background_bundle(binary)
    info.write_bytes(plistlib.dumps({'LSUIElement':True}));audit.validate_background_bundle(binary)
 def test_other_platforms_do_not_require_apple_bundle(self):
  from unittest.mock import patch
  with patch.object(audit.sys,'platform','win32'):audit.validate_background_bundle(Path('/tmp/client.exe'))
