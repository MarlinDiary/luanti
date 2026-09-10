"""Regression for real-server recover_air() on already dry ground."""
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course.skills import regain_air,Failure

class AirRecoveryTests(unittest.TestCase):
 def context(self,breaths,dry=True):
  self.clock=0.;self.reads=0
  def read(radius=0):
   b=breaths[min(self.reads,len(breaths)-1)];self.reads+=1
   return SimpleNamespace(position=(0,.5,0),yaw=0,raw={'breath':b})
  def sleep(t):self.clock+=t
  world=SimpleNamespace(body_clear=Mock(return_value=dry),start=Mock(return_value=(0,1,0)),
   path=Mock(return_value=([(0,1,0)],None)),surface_water=lambda p:True,point=lambda p:(0,.55,0))
  return SimpleNamespace(world=world,read=read,sleep=sleep,deadline=.4,blocked=set(),within=lambda p:True,
   log=Mock(),stop_input=Mock(),resurfacing=False,details={},game=SimpleNamespace(_submit=Mock()))
 def execute(self,c):
  with patch('luanti_course.skills.time.monotonic',side_effect=lambda:self.clock),patch('luanti_course.skills.follow_path',return_value=(True,None)) as follow:
   regain_air(c)
   return follow
 def test_dry_ground_maximum_ten_is_already_recovered(self):
  c=self.context([10]);follow=self.execute(c)
  self.assertFalse(c.world.path.called);self.assertFalse(follow.called)
  self.assertEqual(c.details['outcome'],'already_breathing');self.assertFalse(c.resurfacing)
  c.game._submit.assert_not_called()
 def test_low_breath_on_dry_ground_waits_without_seeking_water(self):
  c=self.context([3,6,9]);self.execute(c)
  self.assertEqual(c.details['outcome'],'breath_recovered');self.assertEqual(self.reads,3)
  c.world.path.assert_not_called();c.game._submit.assert_not_called()
 def test_dry_ground_recovery_requires_observed_confirmation(self):
  c=self.context([3])
  with self.assertRaises(Failure) as e:self.execute(c)
  self.assertEqual(e.exception.reason,'breath_recovery_unconfirmed')
  self.assertFalse(c.resurfacing);c.stop_input.assert_called()
 def test_submerged_full_breath_still_uses_surface_route(self):
  c=self.context([10],dry=False);follow=self.execute(c)
  c.world.path.assert_called_once();follow.assert_called_once()
 def test_unknown_body_does_not_short_circuit_to_success(self):
  c=self.context([10],dry=False);c.world.path.return_value=(None,None)
  with self.assertRaises(Failure) as e:self.execute(c)
  self.assertEqual(e.exception.reason,'air_route_unavailable')
 def test_becoming_wet_during_wait_replans(self):
  c=self.context([3,3,10]);c.world.body_clear.side_effect=[True,False]
  follow=self.execute(c);c.world.path.assert_called_once();follow.assert_called_once()
 def test_control_loss_during_dry_wait_cleans_up(self):
  c=self.context([3]);s=c.read();c.read=Mock(side_effect=[s,Failure('control_released',status='cancelled')])
  with self.assertRaises(Failure) as e:self.execute(c)
  self.assertEqual(e.exception.reason,'control_released');self.assertFalse(c.resurfacing);c.stop_input.assert_called()
if __name__=='__main__':unittest.main()
