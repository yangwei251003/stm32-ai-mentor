"""Initialize a new demonstration profile; never copy private learner data."""
from pathlib import Path
import subprocess,sys,argparse,shutil
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--test-config',action='store_true');a=p.parse_args()
state=ROOT/'Student_Profile';command='validate' if state.exists() else 'init'
subprocess.run([sys.executable,str(ROOT/'.agents/skills/stm32-ai-mentor/scripts/state_tool.py'),'--profile-dir',str(state),command],check=True)
if a.test_config:
 target=ROOT/'.codex'
 if target.exists():raise SystemExit('Existing .codex configuration: review manually; no overwrite.')
 shutil.copytree(ROOT/'examples/codex',target)
 for name in ['.playwright-mcp','%USERPROFILE%']:(ROOT/name).mkdir(exist_ok=True)
 print('Historical test scaffold copied. It contains no executable MCP registration.')
