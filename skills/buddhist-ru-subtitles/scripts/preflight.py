"""Check local resources, not linguistic quality; no network or writes."""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def inspect(glossary=None):
    if sys.version_info < (3, 11):
        raise ValueError('Python 3.11+ required')
    refs = Path(__file__).resolve().parents[1] / 'references'
    config = json.loads((refs / 'resources.json').read_text('utf-8'))
    path = Path(glossary).expanduser().resolve() if glossary else refs / config['glossary']['selected']
    data = path.read_bytes()
    text = data.decode('utf-8-sig')
    count = sum('：' in line for line in text.splitlines())
    digest = hashlib.sha256(data).hexdigest()
    if not count:
        raise ValueError('No glossary entries detected; inspect custom format before translation')
    if not glossary and (digest != config['glossary']['sha256'] or count != config['glossary']['entry_count']):
        raise ValueError('Bundled glossary changed; inspect version before proceeding')
    rules = refs / config['translation_rules']
    rules.read_text('utf-8-sig')
    return {'glossary': str(path), 'sha256': digest, 'entry_count': count,
            'custom_glossary': bool(glossary), 'rules': str(rules),
            'rules_sha256': hashlib.sha256(rules.read_bytes()).hexdigest(),
            'agent_must_read_full_resources': True, 'premiere_required': False,
            'linguistic_quality_verified': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--glossary', help='Explicit UTF-8 custom glossary; never silently falls back')
    a = p.parse_args()
    try:
        print(json.dumps(inspect(a.glossary), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        p.exit(1, str(exc) + '\n')
