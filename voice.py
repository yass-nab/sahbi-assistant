"""Voice out: natural local voice with Piper (neural TTS, CPU), Windows voice as fallback.
speak() blocks until the sound ends, so the caller can keep the microphone muted exactly that long."""
import io, re, subprocess, threading, wave, winsound
from pathlib import Path

import config

NO_WINDOW = 0x08000000
_voice, _lock = None, threading.Lock()
enabled = True


def _load():
    global _voice
    if _voice is None:
        p = Path(config.get('voice_model'))
        if p.exists():
            from piper import PiperVoice
            _voice = PiperVoice.load(str(p))
    return _voice


def clean(text):
    text = re.sub(r'https?://\S+', 'the link', text)
    text = re.sub(r'[A-Za-z]:\\[^\s,]+', 'the file', text)
    return re.sub(r'[*_`#>\[\]|]', '', text).strip()[:700]


def _wav(text):
    v = _load()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        if hasattr(v, 'synthesize_wav'):            # piper-tts >= 1.3
            v.synthesize_wav(text, w)
        else:                                       # older piper-tts
            v.synthesize(text, w)
    return buf.getvalue()


def speak(text):
    """Speak and wait until finished. Returns True if something was played."""
    text = clean(text)
    if not text or not enabled:
        return False
    with _lock:
        try:
            if _load() is not None:
                winsound.PlaySound(_wav(text), winsound.SND_MEMORY)
                return True
        except Exception:  # noqa: BLE001
            pass
        t = text.replace("'", "''")
        subprocess.run(['powershell', '-NoProfile', '-Command',
                        "Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                        "try{$s.SelectVoice('Microsoft Zira Desktop')}catch{}; $s.Speak('" + t + "')"],
                       creationflags=NO_WINDOW)
        return True


def warm():
    try:
        _load()
    except Exception:  # noqa: BLE001
        pass
