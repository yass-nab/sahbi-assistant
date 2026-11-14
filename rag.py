"""Chat with your documents: index the Workspace (PDF, Word, PowerPoint, notebooks, text) with a local embedding
model (Ollama nomic-embed-text) and find the passages that answer a question. Index lives in data/index/.

  python rag.py            build / update the index (incremental, only changed files)
  python rag.py "question" search it
"""
import json, os, re, sys, threading, time, zipfile
from pathlib import Path

import numpy as np
import requests

import config

OLLAMA = 'http://127.0.0.1:11434'
IDX = config.DATA / 'index'
IDX.mkdir(exist_ok=True)
EXTS = {'.pdf', '.docx', '.pptx', '.ipynb', '.md', '.txt'}
MAX_MB = 25
CHUNK, OVERLAP = 900, 150
_lock = threading.Lock()
status = {'state': 'idle', 'files': 0, 'chunks': 0, 'done': 0, 'todo': 0}
try:                                   # show the existing index right away after a restart
    _m = json.loads((IDX / 'meta.json').read_text(encoding='utf-8'))
    status.update(state='ready', files=len(_m['files']), chunks=len(_m['chunks']))
except (OSError, ValueError, KeyError):
    pass


# ------------------------------------------------------------------ reading files
def extract(p: Path) -> str:
    ext = p.suffix.lower()
    if ext == '.pdf':
        from pypdf import PdfReader
        r = PdfReader(str(p))
        return '\n'.join((pg.extract_text() or '') for pg in r.pages[:60])
    if ext in ('.docx', '.pptx'):
        z = zipfile.ZipFile(p)
        names = ['word/document.xml'] if ext == '.docx' else sorted(
            (n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml', n)), key=lambda n: int(re.findall(r'\d+', n)[0]))
        out = []
        for n in names:
            xml = z.read(n).decode('utf-8', 'ignore').replace('</w:p>', '\n').replace('</a:p>', '\n')
            out.append(re.sub(r'<[^>]+>', '', xml))
        return '\n'.join(out)
    if ext == '.ipynb':
        nb = json.loads(p.read_text(encoding='utf-8', errors='ignore'))
        return '\n\n'.join(''.join(c.get('source', '')) for c in nb.get('cells', []))
    return p.read_text(encoding='utf-8', errors='ignore')


def chunks(text):
    text = re.sub(r'[ \t]+', ' ', re.sub(r'\n{3,}', '\n\n', text)).strip()
    out, i = [], 0
    while i < len(text):
        piece = text[i:i + CHUNK]
        if len(piece.strip()) > 80:
            out.append(piece)
        i += CHUNK - OVERLAP
    return out


def files():
    root = Path(config.get('workspace'))
    private = [x.lower() for x in config.get('private_folders')]
    skip = {s.lower() for s in config.get('skip_dirs')}
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip and not d.startswith('.')
                   and not any(x.strip('\\') == d.lower() for x in private)]
        for n in names:
            p = Path(dirpath) / n
            low = str(p).lower()
            if p.suffix.lower() in EXTS and not any(x in low for x in private):
                try:
                    if p.stat().st_size <= MAX_MB * 1024 * 1024:
                        yield p
                except OSError:
                    pass


# ------------------------------------------------------------------ embeddings
def embed(texts, prefix):
    r = requests.post(f'{OLLAMA}/api/embed', json={'model': config.get('embed_model'), 'keep_alive': '5m',
                                                   'input': [prefix + t for t in texts]}, timeout=300)
    r.raise_for_status()
    v = np.array(r.json()['embeddings'], dtype=np.float32)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def _load():
    meta = json.loads((IDX / 'meta.json').read_text(encoding='utf-8')) if (IDX / 'meta.json').exists() else {'files': {}, 'chunks': []}
    vecs = np.load(IDX / 'vecs.npy') if (IDX / 'vecs.npy').exists() else np.zeros((0, 768), np.float32)
    return meta, vecs


def build(log=print):
    """Incremental: re-embed only new/changed files, drop deleted ones."""
    if not _lock.acquire(blocking=False):
        return 'Indexing is already running.'
    try:
        status.update(state='scanning')
        meta, vecs = _load()
        current = {str(p): p.stat().st_mtime for p in files()}
        keep = [i for i, c in enumerate(meta['chunks']) if current.get(c['file']) == meta['files'].get(c['file'])]
        chunks_meta = [meta['chunks'][i] for i in keep]
        vecs = vecs[keep] if len(vecs) else vecs
        known = {f for f, m in meta['files'].items() if current.get(f) == m}
        todo = [f for f in current if f not in known]
        status.update(state='indexing', todo=len(todo), done=0, files=len(current))
        new_files = {f: current[f] for f in known}
        t0 = time.time()
        for k, f in enumerate(todo, 1):
            try:
                parts = chunks(extract(Path(f)))[:200]
            except Exception as e:  # noqa: BLE001
                log(f'skip {Path(f).name}: {e}')
                new_files[f] = current[f]
                continue
            for b in range(0, len(parts), 32):
                batch = parts[b:b + 32]
                v = embed(batch, 'search_document: ')
                vecs = np.vstack([vecs, v]) if len(vecs) else v
                chunks_meta += [{'file': f, 'text': t} for t in batch]
            new_files[f] = current[f]
            status.update(done=k, chunks=len(chunks_meta))
            if k % 25 == 0 or k == len(todo):
                _save(new_files, chunks_meta, vecs)
                log(f'indexed {k}/{len(todo)} files, {len(chunks_meta)} passages ({time.time() - t0:.0f}s)')
        _save(new_files, chunks_meta, vecs)
        status.update(state='ready', chunks=len(chunks_meta), files=len(new_files))
        return f'Index ready: {len(new_files)} files, {len(chunks_meta)} passages.'
    finally:
        _lock.release()


def _save(files_map, chunks_meta, vecs):
    np.save(IDX / 'vecs.npy', vecs)
    (IDX / 'meta.json').write_text(json.dumps({'files': files_map, 'chunks': chunks_meta}, ensure_ascii=False),
                                   encoding='utf-8')


def search(question, k=5):
    meta, vecs = _load()
    if not len(vecs):
        return []
    q = embed([question], 'search_query: ')[0]
    sims = vecs @ q
    best, seen, out = np.argsort(-sims)[:k * 3], {}, []
    for i in best:
        c = meta['chunks'][int(i)]
        if seen.get(c['file'], 0) >= 2:
            continue
        seen[c['file']] = seen.get(c['file'], 0) + 1
        out.append({'file': c['file'], 'score': round(float(sims[i]), 3), 'text': c['text']})
        if len(out) == k:
            break
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) > 1:
        for h in search(' '.join(sys.argv[1:])):
            print(f"{h['score']}  {Path(h['file']).name}\n   {h['text'][:200]}\n")
    else:
        print(build())


# ------------------------------------------------------------------ bubble map (topics of your documents)
STOP = set('the and for with from this that your you are pdf docx pptx ipynb txt md les des une pour avec dans sur par '
           'copy final new old version untitled document notebook file files cours chapitre chapter part page des du de la le'.split())


def _kmeans(X, k, iters=30, seed=7):
    rng = np.random.default_rng(seed)
    C = [X[rng.integers(len(X))]]
    for _ in range(1, k):                                   # k-means++ start
        d = np.min([1 - X @ c for c in C], axis=0).clip(1e-9)
        C.append(X[rng.choice(len(X), p=d / d.sum())])
    C = np.array(C)
    for _ in range(iters):
        lab = np.argmax(X @ C.T, axis=1)
        for j in range(k):
            m = X[lab == j]
            if len(m):
                c = m.mean(0)
                C[j] = c / (np.linalg.norm(c) + 1e-9)
    return np.argmax(X @ C.T, axis=1), C


def _words(path):
    rel = str(Path(path)).lower()
    toks = re.findall(r'[a-zà-ÿ]{3,}', Path(rel).stem) * 2 + re.findall(r'[a-zà-ÿ]{3,}', Path(rel).parent.name)
    return [t for t in toks if t not in STOP]


def _folder(path):
    try:
        parts = Path(path).relative_to(Path(config.get('workspace'))).parts
    except ValueError:
        parts = Path(path).parts
    name = parts[1] if len(parts) > 2 else parts[0]
    return re.sub(r'^\d+\s*', '', name)


def map_data():
    cache = IDX / 'map.json'
    meta_file = IDX / 'meta.json'
    if cache.exists() and meta_file.exists() and cache.stat().st_mtime >= meta_file.stat().st_mtime:
        return json.loads(cache.read_text(encoding='utf-8'))
    meta, vecs = _load()
    if not len(vecs):
        return {'clusters': [], 'nodes': []}
    by_file = {}
    for i, c in enumerate(meta['chunks']):
        by_file.setdefault(c['file'], []).append(i)
    files_ = list(by_file)
    X = np.array([vecs[by_file[f]].mean(0) for f in files_])
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    k = int(min(10, max(3, len(files_) // 40)))
    lab, C = _kmeans(X, k)
    # topic names: words frequent inside the cluster but rare elsewhere
    from collections import Counter
    total = Counter(w for f in files_ for w in set(_words(f)))
    clusters = []
    for j in range(k):
        members = [f for f, l in zip(files_, lab) if l == j]
        folders = Counter(_folder(f) for f in members).most_common(3)
        best = [n for n, c in folders if c >= max(2, 0.18 * len(members))][:2]
        if not best:
            cnt = Counter(w for f in members for w in set(_words(f)))
            best = [w.capitalize() for w in sorted(cnt, key=lambda w: -(cnt[w] / (total[w] + 2)) * min(cnt[w], 6))[:2]]
        clusters.append({'id': j, 'label': ' · '.join(best) or f'Topic {j + 1}', 'count': len(members)})
    seen = Counter(c['label'] for c in clusters)            # same folder twice -> add a distinguishing word
    for j, c in enumerate(clusters):
        if seen[c['label']] > 1:
            members = [f for f, l in zip(files_, lab) if l == j]
            cnt = Counter(w for f in members for w in set(_words(f)))
            w = sorted(cnt, key=lambda w: -(cnt[w] / (total[w] + 2)) * min(cnt[w], 6))[:1]
            if w:
                c['label'] = f"{c['label'].split(' · ')[0]} · {w[0].capitalize()}"
    # place topics: 2-D PCA of the topic centres, so related topics sit close together
    Cc = C - C.mean(0)
    _, _, vt = np.linalg.svd(Cc, full_matrices=False)
    P = Cc @ vt[:2].T
    P = P / (np.abs(P).max(0) + 1e-9)
    for j, c in enumerate(clusters):
        c['x'], c['y'] = round(float(P[j, 0]), 3), round(float(P[j, 1]), 3)
    root = Path(config.get('workspace'))
    nodes = []
    for f, l in zip(files_, lab):
        p = Path(f)
        try:
            rel = str(p.relative_to(root))
        except ValueError:
            rel = p.name
        nodes.append({'name': p.stem, 'ext': p.suffix.lower().lstrip('.'), 'path': f, 'rel': rel,
                      'cluster': int(l), 'size': len(by_file[f])})
    # links (like a holders bubble map): each document -> its most similar documents, each topic -> nearest topics
    S = X @ X.T
    np.fill_diagonal(S, 0)
    links, seen_pairs = [], set()
    for i in range(len(files_)):
        for j in np.argsort(-S[i])[:3]:
            a, b = sorted((i, int(j)))
            if S[i, j] >= 0.80 and (a, b) not in seen_pairs:
                seen_pairs.add((a, b))
                links.append({'a': a, 'b': b, 'w': round(float((S[i, j] - 0.8) / 0.2), 3)})
    CS = C @ C.T
    np.fill_diagonal(CS, -1)
    tlinks, tseen = [], set()
    for i in range(k):
        for j in np.argsort(-CS[i])[:3]:
            a, b = sorted((i, int(j)))
            if (a, b) not in tseen:
                tseen.add((a, b))
                tlinks.append({'a': a, 'b': b, 'w': round(float(CS[i, j]), 3)})
    lo, hi = min(l['w'] for l in tlinks), max(l['w'] for l in tlinks)
    for l in tlinks:
        l['w'] = round((l['w'] - lo) / (hi - lo + 1e-9), 3)
    np.save(IDX / 'filevecs.npy', X)
    out = {'clusters': clusters, 'nodes': nodes, 'links': links, 'topic_links': tlinks}
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return out


def doc_detail(path, max_parts=28):
    """One document 'opened up': its passages and the most related documents anywhere in the Workspace."""
    data = map_data()
    files_ = [n['path'] for n in data['nodes']]
    if path not in files_:
        return None
    meta, _ = _load()
    parts = [c['text'] for c in meta['chunks'] if c['file'] == path]
    step = max(1, len(parts) // max_parts)
    parts = [' '.join(t.split()) for t in parts[::step][:max_parts]]
    X = np.load(IDX / 'filevecs.npy')
    i = files_.index(path)
    sims = X @ X[i]
    sims[i] = -1
    related = [{**data['nodes'][int(j)], 'w': round(float(sims[j]), 3)} for j in np.argsort(-sims)[:10]]
    return {'node': data['nodes'][i], 'parts': parts, 'related': related}
