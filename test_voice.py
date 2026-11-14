"""Voice test without a microphone: feeds WAV files into Sahbi's ears as if spoken, in order.
  python test_voice.py wake.wav cmd.wav      (16 kHz mono 16-bit WAVs)
Needs Ollama running. Prints what was heard and Sahbi's reply."""
import sys, threading, time, wave
import numpy as np
import sahbi

sahbi.webbrowser.open = lambda url: print('[would open browser]', url)
sahbi.say = lambda text, wait=False: print('[says]', text)
sahbi.voice.enabled = False
sahbi.push = lambda kind, **d: print(f'[{kind}]', d) if kind in ('heard', 'reply', 'action', 'wake') else None

ears = sahbi.Ears()
ears.unmute = lambda: setattr(ears, 'muted', False)
threading.Thread(target=ears.loop, daemon=True).start()

silence = np.zeros(ears.BLOCK, dtype='float32')
for path in sys.argv[1:]:
    w = wave.open(path)
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype('float32') / 32768
    for _ in range(30):
        ears.audio.put(silence)
    for i in range(0, len(a), ears.BLOCK):
        blk = a[i:i + ears.BLOCK]
        ears.audio.put(np.pad(blk, (0, ears.BLOCK - len(blk))))
        time.sleep(0.03)
    for _ in range(40):
        ears.audio.put(silence); time.sleep(0.03)
    time.sleep(3.2)          # like a person pausing after the greeting
time.sleep(12)
