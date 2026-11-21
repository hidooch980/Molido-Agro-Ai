import importlib.util
import sys
from pathlib import Path
MODULE=Path(__file__).resolve().parents[1]/'scripts'/'bughunter_agent.py'
SPEC=importlib.util.spec_from_file_location('bughunter_agent',MODULE)
AGENT=importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name]=AGENT; SPEC.loader.exec_module(AGENT)
def test_classifies_dependency_migration_and_permissions():
 assert 'dependency' in AGENT.classify('ModuleNotFoundError: No module named x')
 assert 'migration' in AGENT.classify('sqlite no such column')
 assert 'permissions' in AGENT.classify('HTTP 403 forbidden')
 assert AGENT.classify("NameError: name 'Path' is not defined") == ['test_harness_path']
 assert AGENT.classify("can't open file '/repo/server/backup_db.py'") == ['test_harness_path']
def test_unknown_failure_is_preserved():
 assert AGENT.classify('unrecognized failure') == ['unclassified_failure']
def test_autofix_is_disabled_by_default():
 assert AGENT.safe_fixes(False) == {'enabled':False,'status':'not_requested','changed_files':[]}
def test_agent_has_no_release_or_data_mutation_capability():
 source=MODULE.read_text(encoding='utf-8')
 assert 'database_or_user_data_mutation' in source and 'merge_or_release_permission' in source

def test_safe_autofix_rollback_restores_only_server_python_files(tmp_path, monkeypatch):
 root = tmp_path
 target = root / 'server' / 'sample.py'
 target.parent.mkdir()
 target.write_bytes(b'fixed = True\n')
 monkeypatch.setattr(AGENT, 'ROOT', root)
 restored = AGENT.rollback_safe_fixes({'server/sample.py': b'fixed = False\n'}, ['server/sample.py', '../outside.py', 'server/data.db'])
 assert restored == ['server/sample.py']
 assert target.read_bytes() == b'fixed = False\n'


def test_safe_autofix_rollback_does_not_touch_unchanged_files(tmp_path, monkeypatch):
 target = tmp_path / 'server' / 'same.py'
 target.parent.mkdir()
 target.write_bytes(b'value = 1\n')
 monkeypatch.setattr(AGENT, 'ROOT', tmp_path)
 assert AGENT.rollback_safe_fixes({'server/same.py': b'value = 1\n'}, ['server/same.py']) == []

def test_safe_autofix_rollback_restores_deleted_server_file(tmp_path, monkeypatch):
 target = tmp_path / 'server' / 'deleted.py'
 target.parent.mkdir()
 monkeypatch.setattr(AGENT, 'ROOT', tmp_path)
 restored = AGENT.rollback_safe_fixes({'server/deleted.py': b'value = 7\\n'}, ['server/deleted.py'])
 assert restored == ['server/deleted.py']
 assert target.read_bytes() == b'value = 7\\n'

def test_safe_autofix_rollback_removes_new_server_file(tmp_path, monkeypatch):
 target = tmp_path / 'server' / 'created.py'
 target.parent.mkdir()
 target.write_bytes(b'created = True\\n')
 monkeypatch.setattr(AGENT, 'ROOT', tmp_path)
 restored = AGENT.rollback_safe_fixes({}, ['server/created.py'])
 assert restored == ['server/created.py']
 assert not target.exists()
