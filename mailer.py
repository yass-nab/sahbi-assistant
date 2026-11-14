"""Gmail for Sahbi: send (SMTP) and read (IMAP) with a Google App Password.

The App Password is stored encrypted with Windows DPAPI (only your Windows account on this PC can decrypt it):
  %APPDATA%\\Sahbi\\gmail.json  ->  {"address": "...", "secret": "<DPAPI blob, base64>"}
Run "Setup Sahbi email.bat" once to store it.
"""
import base64, ctypes, ctypes.wintypes as wt, email, imaplib, json, mimetypes, os, re, smtplib, ssl
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr, parsedate_to_datetime
from pathlib import Path

import config

CONF = Path(os.environ.get('APPDATA', '')) / 'Sahbi' / 'gmail.json'
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
PRIVATE = tuple(config.get('private_folders')) + ('\\sahbi\\gmail',)
MAX_MB = 20


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError('DPAPI failed')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def save(address, app_password):
    CONF.parent.mkdir(parents=True, exist_ok=True)
    blob = base64.b64encode(_dpapi(app_password.replace(' ', '').encode(), True)).decode()
    CONF.write_text(json.dumps({'address': address, 'secret': blob}), encoding='utf-8')


def _load():
    if not CONF.exists():
        return None, None
    c = json.loads(CONF.read_text(encoding='utf-8'))
    return c['address'], _dpapi(base64.b64decode(c['secret']), False).decode()


def ready():
    return CONF.exists()


def address():
    return _load()[0] if ready() else None


# ------------------------------------------------------------------ sending
def check(to, attachments):
    """Validate before scheduling. Returns (clean_to_list, attachment_paths, error)."""
    tos = [t.strip() for t in re.split(r'[,; ]+', str(to)) if t.strip()]
    if not tos:
        return None, None, 'No recipient.'
    bad = [t for t in tos if not EMAIL_RE.match(t)]
    if bad:
        return None, None, f'Not a valid email address: {", ".join(bad)}'
    files = []
    for a in attachments or []:
        p = Path(str(a))
        if any(x in str(p.resolve()).lower() for x in PRIVATE):
            return None, None, f'Refused: {p.name} is in a private folder.'
        if not p.is_file():
            return None, None, f'Attachment not found: {p}'
        files.append(p)
    if sum(p.stat().st_size for p in files) > MAX_MB * 1024 * 1024:
        return None, None, f'Attachments are over {MAX_MB} MB.'
    return tos, files, None


def send(to_list, subject, body, files=(), in_reply_to=None):
    addr, pw = _load()
    if not addr:
        raise RuntimeError('Email not set up: run "Setup Sahbi email.bat".')
    m = EmailMessage()
    m['From'] = formataddr((config.get('user_name'), addr))
    m['To'] = ', '.join(to_list)
    m['Subject'] = subject
    m['Message-ID'] = make_msgid(domain='gmail.com')
    if in_reply_to:
        m['In-Reply-To'] = in_reply_to
        m['References'] = in_reply_to
    m.set_content(body)
    for p in files:
        ctype = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        main, sub = ctype.split('/', 1)
        m.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context(), timeout=60) as s:
        s.login(addr, pw)
        s.send_message(m)        # Gmail keeps a copy in Sent automatically


def test_login(addr, pw):
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(addr, pw.replace(' ', ''))


# ------------------------------------------------------------------ reading
FILTERS = {
    'unread': 'is:unread category:primary newer_than:7d',
    'important': 'is:important is:unread newer_than:7d -category:promotions -category:social',
    'recruiters': '(entretien OR interview OR candidature OR application OR recrutement OR recruitment OR offre '
                  'OR poste OR position OR "job" OR rh OR hr) newer_than:30d -category:promotions -category:social',
    'today': 'newer_than:1d category:primary',
}


def _imap():
    addr, pw = _load()
    if not addr:
        raise RuntimeError('Email not set up: run "Setup Sahbi email.bat".')
    M = imaplib.IMAP4_SSL('imap.gmail.com', 993, ssl_context=ssl.create_default_context())
    M.login(addr, pw)
    M.select('INBOX', readonly=True)
    return M


def _h(v):
    try:
        return str(make_header(decode_header(v or '')))
    except Exception:  # noqa: BLE001
        return v or ''


def _text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain' and 'attachment' not in str(part.get('Content-Disposition')):
                return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace')
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                html = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace')
                return re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(script|style).*?</\1>', ' ', html))
        return ''
    body = msg.get_payload(decode=True) or b''
    text = body.decode(msg.get_content_charset() or 'utf-8', 'replace')
    return re.sub(r'<[^>]+>', ' ', text) if msg.get_content_type() == 'text/html' else text


def inbox(kind='important', limit=8, query=None):
    """Newest matching messages: [{uid, from, email, subject, date, snippet}]."""
    raw = query or FILTERS.get(kind, FILTERS['important'])
    M = _imap()
    try:
        typ, data = M.uid('SEARCH', 'X-GM-RAW', f'"{raw}"')
        uids = (data[0] or b'').split()[-limit:][::-1]
        out = []
        for uid in uids:
            typ, d = M.uid('FETCH', uid, '(BODY.PEEK[]<0.20000>)')   # PEEK = don't mark as read
            msg = email.message_from_bytes(d[0][1])
            name, addr = parseaddr(_h(msg.get('From')))
            try:
                date = parsedate_to_datetime(msg.get('Date')).strftime('%d %b %H:%M')
            except Exception:  # noqa: BLE001
                date = ''
            out.append({'uid': uid.decode(), 'from': name or addr, 'email': addr, 'subject': _h(msg.get('Subject')),
                        'date': date, 'snippet': ' '.join(_text(msg).split())[:220]})
        return out
    finally:
        M.logout()


def read(uid):
    M = _imap()
    try:
        typ, d = M.uid('FETCH', str(uid).encode(), '(BODY.PEEK[])')
        if not d or not d[0]:
            return None
        msg = email.message_from_bytes(d[0][1])
        name, addr = parseaddr(_h(msg.get('From')))
        return {'uid': str(uid), 'from': name or addr, 'email': addr, 'subject': _h(msg.get('Subject')),
                'message_id': msg.get('Message-ID'), 'date': msg.get('Date'),
                'body': ' '.join(_text(msg).split())[:4000]}
    finally:
        M.logout()


def unread_counts():
    M = _imap()
    try:
        res = {}
        for k in ('important', 'recruiters'):
            raw = FILTERS[k] + (' is:unread' if k == 'recruiters' else '')
            typ, data = M.uid('SEARCH', 'X-GM-RAW', f'"{raw}"')
            res[k] = len((data[0] or b'').split())
        return res
    finally:
        M.logout()
