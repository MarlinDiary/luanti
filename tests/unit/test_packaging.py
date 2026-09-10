import json,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

class PackagingTests(unittest.TestCase):
    def test_windows_packager_preserves_input_and_verifies_exe(self):
        with tempfile.TemporaryDirectory() as t:
            t=Path(t);source=t/'source';(source/'bin').mkdir(parents=True);(source/'builtin').mkdir()
            (source/'bin/luanti.exe').write_bytes(b'MZ fixture');(source/'builtin/init.lua').write_text('-- fixture')
            out=t/'course.zip'
            before=(source/'bin/luanti.exe').read_bytes()
            subprocess.run([sys.executable,str(ROOT/'tools/package_windows.py'),'--source',str(source),'--output',str(out)],check=True,capture_output=True)
            self.assertEqual((source/'bin/luanti.exe').read_bytes(),before)
            with zipfile.ZipFile(out) as z:self.assertIsNone(z.testzip());self.assertIn('Luanti Course/bin/luanti.exe',z.namelist())
            self.assertTrue(json.loads((Path(str(out)+'.json')).read_text())['contains_exe'])

    def test_release_workflow_has_native_platform_jobs(self):
        text=(ROOT/'.github/workflows/course-release.yml').read_text()
        self.assertIn('runs-on: windows-latest',text);self.assertIn('runs-on: macos-15',text)
        self.assertIn('python tools/prepare_engine.py upstream',text)
        self.assertEqual(text.count('-DBUILD_UNITTESTS=FALSE'),2)
        self.assertEqual(text.count('-DENABLE_POSTGRESQL=FALSE'),2)

if __name__=='__main__':unittest.main()
