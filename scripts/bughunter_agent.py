#!/usr/bin/env python3
"""Bounded, evidence-first diagnostics for Molido Agro AI."""
from __future__ import annotations
import argparse, json, re, shutil, subprocess, sys, time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RULES = {
 'test_harness_path': re.compile(r"can't open file|FileNotFoundError|No such file or directory|NameError: name 'Path' is not defined", re.I),
 'dependency': re.compile(r'ModuleNotFoundError|No module named|Could not resolve', re.I),
 'assertion': re.compile(r'AssertionError|assert ', re.I),
 'migration': re.compile(r'migration|sqlite|no such table|no such column', re.I),
 'android_build': re.compile(r'Execution failed for task|Unresolved reference|Could not compile', re.I),
 'service_network': re.compile(r'Connection refused|timed out|HTTP 5[0-9]{2}', re.I),
 'permissions': re.compile(r'permission denied|unauthorized|forbidden|HTTP 40[13]', re.I),
}
@dataclass
class Check:
 name: str; command: list[str]; status: str; exit_code: int | None
 duration_seconds: float; diagnosis: list[str]; output_tail: str
def classify(output: str) -> list[str]:
 found = [name for name, pattern in RULES.items() if pattern.search(output)]
 if 'test_harness_path' in found: return ['test_harness_path']
 return found or ['unclassified_failure']
def run_check(name: str, command: list[str], timeout: int) -> Check:
 started = time.monotonic()
 try:
  p = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
  out = p.stdout or ''
  return Check(name, command, 'passed' if p.returncode == 0 else 'failed', p.returncode, round(time.monotonic()-started,2), [] if p.returncode == 0 else classify(out), '\n'.join(out.splitlines()[-100:]))
 except subprocess.TimeoutExpired:
  return Check(name, command, 'timed_out', None, round(time.monotonic()-started,2), ['timeout'], 'Check exceeded configured timeout.')
 except OSError as exc:
  return Check(name, command, 'not_run', None, round(time.monotonic()-started,2), ['tool_unavailable'], str(exc))
def snapshot_server_python() -> dict[str, bytes]:
 return {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / 'server').rglob('*.py') if p.is_file()}
def rollback_safe_fixes(snapshot: dict[str, bytes], changed_files: list[str]) -> list[str]:
 restored = []
 for name in changed_files:
  path = Path(name)
  if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'server' or path.suffix != '.py':
   continue
  original = snapshot.get(path.as_posix())
  if original is not None and (ROOT / path).is_file() and (ROOT / path).read_bytes() != original:
   (ROOT / path).write_bytes(original)
   restored.append(path.as_posix())
 return sorted(restored)
def safe_fixes(enabled: bool) -> dict:
 if not enabled: return {'enabled': False, 'status': 'not_requested', 'changed_files': []}
 ruff = shutil.which('ruff')
 if not ruff: return {'enabled': True, 'status': 'skipped_tool_unavailable', 'changed_files': []}
 p = subprocess.run([ruff, 'check', '--fix', '--fix-only', '--select', 'F401,F541,E711,E712', 'server'], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
 global _SAFE_FIX_RESULT_SNAPSHOT
 changed = []
 for name, original in _SAFE_FIX_SNAPSHOT.items():
  path = ROOT / name
  if path.is_file() and path.read_bytes() != original:
   changed.append(name)
 _SAFE_FIX_RESULT_SNAPSHOT = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / 'server').rglob('*.py') if p.is_file()}
 return {'enabled': True, 'status': 'completed' if p.returncode == 0 else 'needs_review', 'exit_code': p.returncode, 'rule_allowlist': ['F401','F541','E711','E712'], 'changed_files': sorted(changed), 'output_tail': '\n'.join((p.stdout or '').splitlines()[-60:])}
def main() -> int:
 ap=argparse.ArgumentParser(); ap.add_argument('--report-dir',default='artifacts/bughunter'); ap.add_argument('--timeout',type=int,default=1800); ap.add_argument('--apply-safe-fixes',action='store_true'); args=ap.parse_args()
 outdir=ROOT/args.report_dir; outdir.mkdir(parents=True,exist_ok=True)
 global _SAFE_FIX_SNAPSHOT, _SAFE_FIX_RESULT_SNAPSHOT
 _SAFE_FIX_SNAPSHOT = snapshot_server_python() if args.apply_safe_fixes else {}
 _SAFE_FIX_RESULT_SNAPSHOT = {}
 fixes=safe_fixes(args.apply_safe_fixes); checks=[]
 if (ROOT/'server').is_dir(): checks.append(run_check('server_pytest',[sys.executable,'-m','pytest','-q','server'],args.timeout))
 if (ROOT/'gradlew').exists(): checks.append(run_check('android_unit_tests',['./gradlew','--no-daemon',':app:testDebugUnitTest'],args.timeout))
 elif shutil.which('gradle') and (ROOT/'app').is_dir(): checks.append(run_check('android_unit_tests',['gradle','--no-daemon',':app:testDebugUnitTest'],args.timeout))
 if not checks: checks.append(Check('discovery',[],'not_run',None,0.0,['no_test_runner'],'No supported test runner found.'))
 passed=sum(c.status=='passed' for c in checks); failed=sum(c.status in ('failed','timed_out') for c in checks)
 current_python = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / 'server').rglob('*.py') if p.is_file()}
 drift = sorted(name for name, expected in _SAFE_FIX_RESULT_SNAPSHOT.items() if current_python.get(name) != expected)
 drift.extend(sorted(set(current_python) - set(_SAFE_FIX_RESULT_SNAPSHOT)))
 if fixes.get('enabled') and fixes.get('changed_files') and (passed != len(checks) or fixes.get('status') != 'completed' or drift):
  rollback_targets = sorted(set(fixes['changed_files']) | set(drift))
  fixes['rollback_files'] = rollback_safe_fixes(_SAFE_FIX_SNAPSHOT, rollback_targets)
  fixes['status'] = 'rolled_back' if fixes['rollback_files'] else 'needs_review'
  fixes['changed_files'] = []
  if drift: fixes['test_side_effects_detected'] = drift
 if fixes.get('status') == 'completed' and fixes.get('changed_files') and passed == len(checks):
  patch = subprocess.run(['git', 'diff', '--binary', '--', *fixes['changed_files']], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
  if patch.returncode == 0 and patch.stdout:
   (outdir/'safe-fixes.patch').write_bytes(patch.stdout)
  else:
   fixes['status'] = 'patch_export_failed'
   fixes['changed_files'] = []
 report={'agent':'Molido BugHunter & AutoFix','schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),'safe_fixes':fixes,'checks':[asdict(c) for c in checks],'totals':{'checks':len(checks),'passed':passed,'failed_or_timed_out':failed,'not_run':sum(c.status=='not_run' for c in checks)},'overall':'passed' if passed==len(checks) and failed==0 else 'needs_attention','safety':{'database_or_user_data_mutation':False,'secret_or_signing_access':False,'merge_or_release_permission':False,'non_deterministic_fixes_require_human_review':True}}
 (outdir/'bughunter-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# Molido BugHunter report','',f"Generated: {report['generated_at']}",f"Overall: {report['overall']}",f"Checks: {len(checks)}; passed: {passed}; failed or timed out: {failed}",'']
 for c in checks: lines += [f'## {c.name}: {c.status}',f'Command: {c.command}',f'Diagnosis: {c.diagnosis}',c.output_tail,'']
 lines += ['## Safety','No database, user data, secrets, signing keys, release tags, deployments, or merges are changed.','Non-deterministic business-logic fixes are escalated for human review.']
 (outdir/'bughunter-report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'overall':report['overall'],'totals':report['totals']})); return 0 if report['overall']=='passed' else 1
if __name__=='__main__': raise SystemExit(main())