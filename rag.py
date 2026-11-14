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
