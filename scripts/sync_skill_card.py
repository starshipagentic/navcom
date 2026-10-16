"""Generate the repository skill card from NavCom's installed-card source."""
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
import navcom

target=root/'skills'/'navcom-session-recall'/'SKILL.md'
if '--check' in sys.argv:
    raise SystemExit(0 if target.read_text()==navcom.SKILL_MD else 'Skill card differs; run scripts/sync_skill_card.py')
target.write_text(navcom.SKILL_MD)
print('Generated '+str(target))
