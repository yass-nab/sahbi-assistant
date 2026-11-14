"""Screen understanding: screenshot -> local vision model (Ollama qwen2.5vl) -> answer."""
import base64, io

import requests
from PIL import ImageGrab

import config

OLLAMA = 'http://127.0.0.1:11434'


def look(question='Describe what is on the screen.'):
    img = ImageGrab.grab(all_screens=False)
    img.thumbnail((1400, 1400))
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=85)
    r = requests.post(f'{OLLAMA}/api/chat', json={
        'model': config.get('vision_model'), 'stream': False, 'keep_alive': '2m',
        'messages': [{'role': 'user', 'images': [base64.b64encode(buf.getvalue()).decode()],
                      'content': f'{question}\nAnswer in English, clearly and briefly. If there is an error message, '
                                 f'quote it and explain the likely fix.'}],
        'options': {'temperature': 0.2, 'num_ctx': 8192}}, timeout=240)
    r.raise_for_status()
    return r.json()['message']['content'].strip()
