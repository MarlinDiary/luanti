import unittest,sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course.skills import use_keys
from luanti_course.navigation import Node
from luanti_course.recipes import RecipeBook
class PlacementPostureTests(unittest.TestCase):
 def context(self,definition,node=None):
  node=node or Node('stone',True,groups={'stone':1})
  return NS(book=NS(items={'stone':definition}),world=NS(nodes={(0,0,0):node}))
 def test_plain_observed_support_does_not_crouch(self):
  self.assertEqual(use_keys(self.context({'on_rightclick':False,'on_receive_fields':False,'groups':{'stone':1}}),(0,0,0)),['place'])
 def test_interactive_support_keeps_sneak(self):
  self.assertEqual(use_keys(self.context({'on_rightclick':True,'groups':{'stone':1}}),(0,0,0)),['sneak','place'])
 def test_unknown_definition_is_conservative(self):
  for d in ({},{'groups':{'stone':1}},{'on_rightclick':None,'groups':{'stone':1}}):
   self.assertEqual(use_keys(self.context(d),(0,0,0)),['sneak','place'])
 def test_changed_live_definition_is_conservative(self):
  self.assertEqual(use_keys(self.context({'on_rightclick':False,'on_receive_fields':False,'groups':{'stone':2}}),(0,0,0)),['sneak','place'])
 def test_unobserved_support_is_conservative(self):
  self.assertEqual(use_keys(self.context({}),(9,0,0)),['sneak','place'])
 def test_air_use_does_not_crouch(self):
  self.assertEqual(use_keys(self.context({}),None),['place'])
 def test_catalog_classifies_plain_and_interactive_nodes(self):
  book=RecipeBook.voxelibre()
  for name,wanted in [('mcl_core:stone',False),('mcl_core:cobble',False),('mcl_core:tree',False),('mcl_furnaces:furnace',False),('mcl_crafting_table:crafting_table',True)]:
   self.assertIs(book.items[name]['on_rightclick'],wanted)
 def test_formspec_support_keeps_sneak_without_rightclick_callback(self):
  self.assertEqual(use_keys(self.context({'on_rightclick':False,'on_receive_fields':True,'groups':{'stone':1}}),(0,0,0)),['sneak','place'])
 def test_missing_formspec_metadata_is_conservative(self):
  self.assertEqual(use_keys(self.context({'on_rightclick':False,'groups':{'stone':1}}),(0,0,0)),['sneak','place'])
 def test_unusable_real_stance_does_not_replan_to_same_rounded_cell(self):
  from luanti_course.skills import place_block
  from luanti_course import InventoryList,Item
  class Checked(Exception):pass
  start=(1,100,2);target=(3,100,4)
  state=NS(position=(.93,99.5,1.86),eye=(.93,101.1,1.86),inventory={'main':InventoryList(9,(Item('stone',3),))})
  world=NS(nodes={target:Node('air',False,buildable=True),(3,99,4):Node('stone',True)},start=lambda p:start,radius=.33,height=1.8)
  calls=[]
  def path(origin,usable,**kw):
   calls.append(1);world.visible=lambda *a:True
   if len(calls)==1:return [start],set()
   self.assertFalse(usable(start));raise Checked()
  world.path=path;world.visible=lambda *a:False
  ctx=NS(book=NS(resolve=lambda x:x,items={'stone':{'type':'node'}}),read=lambda *a:state,world=world,within=lambda p:True,blocked=set())
  with patch('luanti_course.skills.close_form'),patch('luanti_course.skills.navigate',side_effect=AssertionError('no-op stance selected')):
   with self.assertRaises(Checked):place_block(ctx,'stone',target)
if __name__=='__main__':unittest.main()
