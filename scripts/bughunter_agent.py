#!/usr/bin/env python3
"""Bounded, evidence-first diagnostics for Molido Agro AI."""
from __future__ import annotations
import argparse, json, re, shutil, subprocess, sys, time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RULES = {
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
 return found or ['unclassified_failure']
def run_check(name: str, command: list[str], timeout: int) -> Check:
 started = time.monotonic()
 try:
  p = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
  out = p.stdout or ''
  return Check(name, command, 'passed' if p.returncode == 0 else 'failed', p.returncode, round(time.monotonic()-started,2), [] if p.returncode == 0 else classify(out), '\\n'.join(out.splitlines()[-100:]))
 except subprocess.TimeoutExpired:
  return Check(name, command, 'timed_out', None, round(time.monotonic()-started,2), ['timeout'], 'Check exceeded configured timeout.')
 except OSError as exc:
  return Check(name, command, 'not_run', None, round(time.monotonic()-started,2), ['tool_unavailable'], str(exc))
def safe_fixes(enabled: bool) -> dict:
 if not enabled: return {'enabled': False, 'status': 'not_requested', 'changed_files': []}
 ruff = shutil.which('ruff')
 if not ruff: return {'enabled': True, 'status': 'skipped_tool_unavailable', 'changed_files': []}
 p = subprocess.run([ruff, 'check', '--fix', 'server'], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
 s = subprocess.run(['git','status','--porcelain','--','server'], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=False)
 changed = sorted({line[3:].strip() for line in s.stdout.splitlines() if line[3:].strip().endswith('.py')})
 return {'enabled': True, 'status': 'completed' if p.returncode == 0 else 'needs_review', 'exit_code': p.returncode, 'changed_files': changed, 'output_tail': '\\n'.join((p.stdout or '').splitlines()[-60:])}
def main() -> int:
 ap=argparse.ArgumentParser(); ap.add_argument('--report-dir',default='artifacts/bughunter'); ap.add_argument('--timeout',type=int,default=1800); ap.add_argument('--apply-safe-fixes',action='store_true'); args=ap.parse_args()
 outdir=ROOT/args.report_dir; outdir.mkdir(parents=True,exist_ok=True); fixes=safe_fixes(args.apply_safe_fixes); checks=[]
 if (ROOT/'server').is_dir(): checks.append(run_check('server_pytest',[sys.executable,'-m','pytest','-q','server'],args.timeout))
 if (ROOT/'gradlew').exists(): checks.append(run_check('android_unit_tests',['./gradlew','--no-daemon',':app:testDebugUnitTest'],args.timeout))
 elif shutil.which('gradle') and (ROOT/'app').is_dir(): checks.append(run_check('android_unit_tests',['gradle','--no-daemon',':app:testDebugUnitTest'],args.timeout))
 if not checks: checks.append(Check('discovery',[],'not_run',None,0.0,['no_test_runner'],'No supported test runner found.'))
 passed=sum(c.status=='passed' for c in checks); failed=sum(c.status in ('failed','timed_out') for c in checks)
 report={'agent':'Molido BugHunter & AutoFix','schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),'safe_fixes':fixes,'checks':[asdict(c) for c in checks],'totals':{'checks':len(checks),'passed':passed,'failed_or_timed_out':failed,'not_run':sum(c.status=='not_run' for c in checks)},'overall':'passed' if passed==len(checks) and failed==0 else 'needs_attention','safety':{'database_or_user_data_mutation':False,'secret_or_signing_access':False,'merge_or_release_permission':False,'non_deterministic_fixes_require_human_review':True}}
 (outdir/'bughunter-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8')
 lines=['# Molido BugHunter report','',f"Generated: {report['generated_at']}",f"Overall: {report['overall']}",f"Checks: {len(checks)}; passed: {passed}; failed or timed out: {failed}",'']
 for c in checks: lines += [f'## {c.name}: {c.status}',f'Command: {c.command}',f'Diagnosis: {c.diagnosis}',c.output_tail,'']
 lines += ['## Safety','No database, user data, secrets, signing keys, release tags, deployments, or merges are changed.','Non-deterministic business-logic fixes are escalated for human review.']
 (outdir/'bughunter-report.md').write_text('\\n'.join(lines)+'\\n',encoding='utf-8')
 print(json.dumps({'overall':report['overall'],'totals':report['totals']})); return 0 if report['overall']=='passed' else 1
if __name__=='__main__': raise SystemExit(main())