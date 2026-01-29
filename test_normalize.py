import sys
sys.stdout.reconfigure(encoding='utf-8')

from nip_finder.ai_extractor import AIExtractor

extractor = AIExtractor()
tests = [
    'Nu-med Elblag',
    'Nu-med Elbląg',
    'Nu-med Katowice',
    'Dom Lekarski Szczecin',
]

for name in tests:
    base = extractor._extract_base_company_name(name)
    changed = "OK" if base != name else "---"
    print(f'{changed:4} {name:30} -> {base}')
