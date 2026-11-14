"""Job hunter: search Moroccan job boards (ReKrute, Emploi.ma), score offers against your skills, keep an
application log (CSV), and pull contact emails from an offer page so Sahbi can send the CV."""
import csv, html, json, re, time, urllib.parse
from datetime import date, timedelta
from pathlib import Path

import requests

import config

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}
LAST = config.DATA / 'last_jobs.json'
FIELDS = ['date', 'company', 'role', 'email', 'lang', 'status', 'last_update', 'note']
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')


def _clean(s):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', s)).split())


def _rekrute(q):
    url = 'https://www.rekrute.com/offres.html?' + urllib.parse.urlencode({'s': 1, 'p': 1, 'o': 1, 'query': q})
    h = requests.get(url, headers=UA, timeout=20).text
    out = []
    for block in h.split('<li class="post-id"')[1:]:
        m = re.search(r"class='titreJob' href=\"([^\"]+)\">(.*?)</a>", block, re.S)
        if not m:
            continue
        comp = re.search(r'alt="([^"]*)"', block)
        out.append({'title': _clean(m.group(2)), 'company': _clean(comp.group(1)) if comp else '',
                    'url': 'https://www.rekrute.com' + m.group(1), 'site': 'ReKrute',
                    'text': _clean(block)[:600]})
    return out


def _emploi(q):
    url = 'https://www.emploi.ma/recherche-jobs-maroc/' + urllib.parse.quote(q)
    h = requests.get(url, headers=UA, timeout=20).text
    out = []
    for m in re.finditer(r'<h3><a href="(/offre-emploi-maroc/[^"]+)" title="([^"]+)"', h):
        tail = h[m.end():m.end() + 1500]
        comp = re.search(r'card-job-company[^>]*>(.*?)</', tail, re.S)
        out.append({'title': _clean(m.group(2)), 'company': _clean(comp.group(1)) if comp else '',
                    'url': 'https://www.emploi.ma' + m.group(1), 'site': 'Emploi.ma', 'text': _clean(tail)[:600]})
    return out


def score(job):
    text = (job['title'] + ' ' + job.get('text', '')).lower()
    title = job['title'].lower()
    s = 0
    for k in config.get('job_skills'):
        if re.search(r'\b' + re.escape(k) + r'\b', title):
            s += 3
        elif re.search(r'\b' + re.escape(k) + r'\b', text):
            s += 1
    if re.search(r'\b(senior|confirm|lead|manager|directeur|head|10 ans|8 ans|5 ans)\b', text):
        s -= 3
    return max(0, min(10, s))


def search(query=None, city=None, limit=8):
    q = (query or config.get('job_default_query')).strip()
    if city:
        q = f'{q} {city}'
    jobs, errors = [], []
    for fn in (_rekrute, _emploi):
        try:
            jobs += fn(q)
        except Exception as e:  # noqa: BLE001
            errors.append(f'{fn.__name__[1:]}: {e}')
    seen, uniq = set(), []
    for j in jobs:
        key = j['title'].lower()[:60]
        if key not in seen:
            seen.add(key)
            j['score'] = score(j)
            uniq.append(j)
    uniq.sort(key=lambda j: -j['score'])
    top = uniq[:limit]
    for i, j in enumerate(top, 1):
        j['n'] = i
    LAST.write_text(json.dumps(top, ensure_ascii=False, indent=1), encoding='utf-8')
    return top, errors


def offer(n):
    """Details of job #n from the last search, including any contact email found on the page."""
    jobs = json.loads(LAST.read_text(encoding='utf-8')) if LAST.exists() else []
    j = next((x for x in jobs if x.get('n') == int(n)), None)
    if not j:
        return None
    try:
        h = requests.get(j['url'], headers=UA, timeout=20).text
        body = _clean(re.sub(r'(?is)<(script|style).*?</\1>', ' ', h))
        j['emails'] = sorted({e for e in EMAIL_RE.findall(body) if not e.lower().endswith(('.png', '.jpg'))
                              and not any(x in e.lower() for x in ('rekrute.com', 'emploi.ma', 'example'))})
        starts = [body.find(k) for k in ('Poste :', 'Description du poste', 'Missions', 'Profil recherch', 'Description')]
        starts = [s for s in starts if s > 0]
        i = min(starts) if starts else max(0, body.lower().find(j['title'].lower()[:25]))
        j['description'] = body[i:i + 2500]
    except Exception as e:  # noqa: BLE001
        j['emails'], j['description'] = [], f'(could not open the offer: {e})'
    return j


# ------------------------------------------------------------------ application log
def _path():
    return Path(config.get('applications_csv'))


def load():
    p = _path()
    if not p.exists():
        return []
    with open(p, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def save(rows):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)


def log_application(company, role, email='', lang='', note=''):
    rows, today = load(), date.today().isoformat()
    rows.append(dict(date=today, company=company, role=role, email=email, lang=lang, status='sent',
                     last_update=today, note=note))
    save(rows)


def due(days=7):
    cut = (date.today() - timedelta(days=days)).isoformat()
    return [r for r in load() if r['status'] in ('sent', 'followed-up') and (r['last_update'] or r['date']) <= cut]
