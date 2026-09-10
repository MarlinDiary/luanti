import json,re,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

class NativeCompletionTests(unittest.TestCase):
    def test_native_version_is_single_source_consistent(self):
        version=json.loads((ROOT/'engine/upstream.json').read_text())['course_version']
        self.assertEqual(version,'0.9.0')
        for p in ('engine/src/course_bridge.cpp','engine/src/game_course.inc'):
            self.assertIn('"'+version+'"',(ROOT/p).read_text())

    def test_visible_image_hud_is_bounded_and_advertised(self):
        text=(ROOT/'engine/src/game_course.inc').read_text()
        self.assertIn('"hud_images"',text)
        self.assertIn('HUD_ELEM_IMAGE',text)
        self.assertRegex(text,r'hud_images.*size\(\).*128')

if __name__=='__main__':unittest.main()
