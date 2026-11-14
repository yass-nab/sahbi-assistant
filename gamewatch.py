"""Auto game mode: when a game starts, switch Sahbi off (frees the GPU); when the game closes, switch it back on.
Only turns Sahbi back on if IT turned it off - a manual "off" is respected.
Runs hidden from the Startup folder:  pythonw gamewatch.py"""
import os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

import psutil

import config

HERE = Path(__file__).resolve().parent
TOGGLE = HERE / 'sahbi-toggle.ps1'
FLAG = config.DATA / 'auto_gamemode.flag'
LOG = HERE / 'gamewatch.log'
NO_WINDOW = 0x08000000
GAME_DIRS = ('\\steamapps\\common\\', '\\epic games\\', '\\riot games\\', '\\ubisoft game launcher\\games\\',
             '\\ea games\\', '\\gog galaxy\\games\\', '\\xboxgames\\')


def log(*a):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{datetime.now():%Y-%m-%d %H:%M:%S} ' + ' '.join(map(str, a)) + '\n')


def running_game():
    exclude = [x.lower() for x in config.get('games_exclude')]
    extra = {x.lower() for x in config.get('games_extra')}
    for p in psutil.process_iter(['name', 'exe']):
        name, exe = (p.info['name'] or '').lower(), (p.info['exe'] or '').lower()
        if any(x in name for x in exclude):
            continue
        if name in extra or (exe and any(d in exe for d in GAME_DIRS)):
            return p.info['name']
    return None


def sahbi_on():
    return any(c.laddr.port == 8770 and c.status == psutil.CONN_LISTEN
               for c in psutil.net_connections('tcp') if c.laddr)


def toggle(arg):
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                    '-File', str(TOGGLE), arg], creationflags=NO_WINDOW)


def main():
    if sys.stdout is None:
        sys.stdout = sys.stderr = open(os.devnull, 'w')
    seen = gone = 0
    log('watching for games')
    while True:
        try:
            game = running_game()
            if game:
                seen, gone = seen + 1, 0
                if seen == 2 and sahbi_on():                 # seen twice (20 s) -> really playing
                    log('game started:', game, '-> Sahbi off')
                    FLAG.write_text(game, encoding='utf-8')
                    toggle('-Off')
            else:
                seen, gone = 0, gone + 1
                if gone == 3 and FLAG.exists():               # gone for 30 s -> back on
                    log('game closed -> Sahbi on')
                    FLAG.unlink(missing_ok=True)
                    if not sahbi_on():
                        toggle('-On')
        except Exception as e:  # noqa: BLE001
            log('error', repr(e))
        time.sleep(10)


if __name__ == '__main__':
    if '--check' in sys.argv:
        print('game running:', running_game(), '| sahbi on:', sahbi_on())
    else:
        main()
