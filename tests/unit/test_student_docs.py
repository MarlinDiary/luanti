"""Student entry pages describe this checkout, not superseded release limits."""
import ast,inspect,json,re,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'sdk/src'))
from luanti_course import Game,__version__

class StudentDocsTests(unittest.TestCase):
    def test_current_versions_in_student_entries(self):
        native=json.loads((ROOT/'engine/upstream.json').read_text())['course_version']
        for name in ('student-skills.md','skill-workflows.md','skills.md'):
            heading=(ROOT/'docs'/name).read_text().splitlines()[0]
            self.assertIn(__version__,heading,name);self.assertIn(native,heading,name)
    def test_student_table_methods_exist(self):
        text=(ROOT/'docs/student-skills.md').read_text().split('## 最小使用方式')[0]
        for line in text.splitlines():
            if not line.startswith('| `'):continue
            for name in re.findall(r'`([a-z_]\w*)(?:\([^`]*\))?`',line.split('|')[1]):
                self.assertIsNotNone(inspect.getattr_static(Game,name,None),name)
    def test_python_snippets_parse(self):
        for path in (ROOT/'README.md',ROOT/'docs/student-skills.md',ROOT/'docs/skill-workflows.md'):
            for code in re.findall(r'```python\n(.*?)```',path.read_text(),re.S):ast.parse(code,filename=str(path))
    def test_entry_links_resolve(self):
        for path in (ROOT/'README.md',ROOT/'docs/student-skills.md',ROOT/'docs/skill-workflows.md',ROOT/'docs/testing.md'):
            for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
                if '://' in target or target.startswith('#'):continue
                self.assertTrue((path.parent/target.split('#')[0]).exists(),str(path)+': '+target)
    def test_park_is_documented_and_executable(self):
        docs=(ROOT/'docs/testing.md').read_text();source=(ROOT/'tests/integration/test_session.py').read_text()
        self.assertIn('test_session.py park --session',docs)
        self.assertIn("a.operation=='park'",source)

if __name__=='__main__':unittest.main()
