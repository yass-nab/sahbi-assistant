"""Long-term memory: short facts Sahbi keeps forever (data/memory.json), added to every conversation."""
import json, threading
from datetime import date

import config

FILE = config.DATA / 'memory.json'
MAX = 80
_lock = threading.Lock()


def load():
    try:
        return json.loads(FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []


def _save(items):
    FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding='utf-8')


def remember(fact):
    fact = ' '.join(str(fact).split())[:300]
    if not fact:
        return 'Nothing to remember.'
    with _lock:
        items = load()
        if any(i['fact'].lower() == fact.lower() for i in items):
            return 'I already know that.'
        items.append({'fact': fact, 'added': date.today().isoformat()})
        _save(items[-MAX:])
    return f'Saved to memory: {fact}'


def forget(text):
    t = str(text).lower().strip()
    with _lock:
        items = load()
        keep = [i for i in items if t not in i['fact'].lower()]
        _save(keep)
    n = len(items) - len(keep)
    return f'Forgot {n} thing(s).' if n else 'I had nothing like that in memory.'


def as_prompt():
    items = load()
    if not items:
        return ''
    return (f'\n\nLONG-TERM MEMORY (facts {config.first_name()} told you to remember):\n- '
            + '\n- '.join(i['fact'] for i in items))
