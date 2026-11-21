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
def test_unknown_failure_is_preserved():
 assert AGENT.classify('unrecognized failure') == ['unclassified_failure']
def test_autofix_is_disabled_by_default():
 assert AGENT.safe_fixes(False) == {'enabled':False,'status':'not_requested','changed_files':[]}
def test_agent_has_no_release_or_data_mutation_capability():
 source=MODULE.read_text(encoding='utf-8')
 assert 'database_or_user_data_mutation' in source and 'merge_or_release_permission' in source