"""Settings. Personal values live in config.json (not in git); config.example.json shows the shape."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / 'data'          # memory, document index, state - never committed
DATA.mkdir(exist_ok=True)

DEFAULTS = {
    'user_name': 'Your Name',
    'about': 'Works in tech.',
    'city': '',
    'workspace': str(Path.home() / 'Documents'),
    'private_folders': ['account recovery', 'passwords'],
    'skip_dirs': ['.git', 'node_modules', '__pycache__', '.ipynb_checkpoints', 'venv', '.venv'],
    'cv': {},                                  # {"en": "C:/.../cv_en.pdf", "fr": "..."}
    'files_hint': '',                          # e.g. "YN_EN.pdf = CV in English"
    'apps': {},                                # {"spotify": "spotify:", "steam": "C:/.../steam.exe"}
    'beam_dir': '',                            # optional: phone link (Beam) folder with beam_server.py
    'live_data_json': '',                      # optional: JSON with weather/gold/btc/news
    'live_data_refresh': '',                   # optional: PowerShell script that refreshes it
    'applications_csv': str(DATA / 'applications.csv'),
    'model': 'qwen2.5:7b',
    'vision_model': 'qwen2.5vl:3b',
    'embed_model': 'nomic-embed-text',
    'voice_model': str(HERE / 'voices' / 'en_US-lessac-medium.onnx'),
    'wake_words': ['salam sahbi'],
    'job_skills': ['python', 'sql', 'data', 'analyst', 'analytics', 'machine learning', 'ml', 'ai', 'ia',
                   'power bi', 'powerbi', 'excel', 'pandas', 'bi', 'scientist', 'science', 'engineer', 'junior',
                   'stage', 'intern', 'dashboard', 'reporting', 'deep learning', 'nlp', 'cloud'],
    'job_default_query': 'data analyst',
    'games_exclude': ['wallpaper', 'steamwebhelper', 'steamservice', 'gameoverlayui', 'crashhandler', 'unins'],
    'games_extra': [],                         # extra game exe names, e.g. ["valorant.exe", "leagueclient.exe"]
    'brief_after_hour': 5,
}

_file = HERE / 'config.json'
CFG = dict(DEFAULTS)
if _file.exists():
    CFG.update(json.loads(_file.read_text(encoding='utf-8')))


def get(key, default=None):
    return CFG.get(key, default)


def first_name():
    return CFG['user_name'].split()[0]
