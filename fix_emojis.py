"""Fix emojis in Python files for Windows compatibility."""
import os

files = [
    'nip_finder/cache.py',
    'nip_finder/validator.py',
    'nip_finder/apify_client.py',
]

emoji_map = {
    '\u2705': '[OK]',
    '\u274c': '[ERROR]',
    '\u26a0\ufe0f': '[WARN]',
    '\u2714\ufe0f': '[OK]',
    '\U0001f50d': '[SEARCH]',
    '\U0001f4be': '[SAVE]',
    '\u25b6\ufe0f': '[RUN]',
    '\U0001f577\ufe0f': '[SCRAPE]',
    '\U0001f527': '[FIX]',
    '\u2192': '->',
    '\u26a0': '[WARN]',
}

for filepath in files:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        for emoji, replacement in emoji_map.items():
            content = content.replace(emoji, replacement)
        
        if content != original:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f'Fixed: {filepath}')
        else:
            print(f'No changes: {filepath}')

print('Done!')
