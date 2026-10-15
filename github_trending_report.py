#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Skills Trending - AI / Agent Skill report generator
======================================================
One run does all of this:
  1) Fetch the official GitHub Trending daily / weekly / monthly boards
  2) Fetch the top N of each board, per section
     (All-time: GitHub Search sorted by total stars; monthly/weekly/daily:
      same topic plus a date-window search to fill the list)
  3) Classify into AI / Agent Skill, deduplicate across boards, sort by total stars
  4) Render an HTML report (only deduplicated projects, each with a link;
     a curated knowledge base supplies the write-ups, and anything new is
     auto-generated and labelled as such)

Usage:
  - Double-click / run with no arguments: opens the GUI. Choose an output folder,
    tick the boards (All-time / Monthly / Weekly / Daily), set how many items to
    collect per board for AI and Agent Skill (1-100), pick the output scope
    (Everything / Skill projects only / AI projects only), then click
    "Fetch and generate report".
  - Command line: python github_trending_report.py --cli [--out-dir DIR]
            [--boards all-time,monthly,weekly,daily] [--topn-ai 50] [--topn-sk 50]
            [--only all|skill|ai]
Requires only the Python 3 standard library (nothing to pip install).
"""
import argparse
import datetime as _dt
import html as _html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KB_PATH = os.path.join(BASE_DIR, 'kb.json')
UA = {'User-Agent': 'gh-trending-report/1.0', 'Accept': 'application/vnd.github+json'}


def _load_github_token():
    """Read an optional GitHub token from GITHUB_TOKEN / GH_TOKEN.
    With a token the Search API limit goes from 10 to 30 requests per minute,
    which cuts the waiting a lot."""
    for k in ('GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_API_TOKEN'):
        v = (os.environ.get(k) or '').strip()
        if v:
            return v
    return ''

# The token is mutable at runtime: pasting one into the GUI takes effect
# immediately, with no environment change and no restart.
STATE = {'token': _load_github_token(), 'token_ok': None, 'token_login': ''}

def get_token():
    return STATE['token']

def set_token(tok):
    """Set the token, sync it into the request headers, and return the old value."""
    old = STATE['token']
    STATE['token'] = (tok or '').strip()
    STATE['token_ok'] = None      # a new token invalidates the previous check
    STATE['token_login'] = ''
    _sync_auth_header()
    return old

def _sync_auth_header():
    if get_token():
        UA['Authorization'] = 'Bearer ' + get_token()
    else:
        UA.pop('Authorization', None)

_sync_auth_header()

# ---------------------------------------------------------------- helpers

# Note: github.com and raw.githubusercontent.com simply do not answer requests
# that use a non-browser User-Agent (the connection just times out).
# HTML requests must send a browser UA or they reliably fail with WinError 10060.
BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
HTML_HEADERS = {'User-Agent': BROWSER_UA,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9'}

def esc(s):
    return _html.escape(str(s), quote=True)

def fmt(n):
    try:
        return '{:,}'.format(int(n))
    except Exception:
        return str(n)

def log(msg):
    line = '[%s] %s' % (_dt.datetime.now().strftime('%H:%M:%S'), msg)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Rare non-UTF-8 console or redirect: degrade to encodable text instead of crashing
        enc = getattr(sys.stdout, 'encoding', None) or 'ascii'
        print(line.encode(enc, 'replace').decode(enc, 'replace'), flush=True)

def http_get(url, timeout=30, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')

# ---------------------------------------------------------------- 1. Trending boards

ARTICLE_SPLIT = re.compile(r'<article class="Box-row')

def parse_trending(raw):
    """Parse a GitHub Trending page into [{repo, desc, lang, stars, gained, unit}]."""
    items = []
    for b in ARTICLE_SPLIT.split(raw)[1:]:
        b = b[:20000]
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="(/[^"]+)"', b)
        if not m:
            continue
        repo = m.group(1).strip('/')
        d = re.search(r'<p class="col-9 color-fg-muted my-1[^"]*">\s*(.*?)\s*</p>', b, re.S)
        desc = _html.unescape(re.sub(r'<[^>]+>', '', d.group(1)).strip()) if d else ''
        lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', b)
        lang = lang.group(1).strip() if lang else ''
        st = re.search(r'stargazers".*?</svg>\s*([\d,\.kK]+)\s*</a>', b, re.S)
        stars = st.group(1) if st else ''
        g = re.search(r'([\d,\.kK]+)\s*stars\s*(today|this week|this month)', b)
        gained, unit = (g.group(1), g.group(2)) if g else ('', '')
        items.append(dict(repo=repo, desc=desc, lang=lang,
                          stars=stars, gained=gained, unit=unit))
    return items

def to_num(s):
    if not s:
        return 0
    s = str(s).replace(',', '')
    mult = 1
    if s and s[-1] in 'kK':
        mult, s = 1000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0

def fetch_trending_boards(labels=('Daily', 'Weekly', 'Monthly')):
    """Return {board: [...]}, each item carrying repo/desc/lang/stars/gained.
    `labels` selects which boards to fetch."""
    boards = {}
    for label, since in (('Daily', 'daily'), ('Weekly', 'weekly'), ('Monthly', 'monthly')):
        if label not in labels:
            continue
        url = 'https://github.com/trending?since=%s' % since
        items = []
        for attempt in (1, 2, 3):
            try:
                items = parse_trending(http_get(url, timeout=35, headers=HTML_HEADERS))
                if items:
                    break
            except Exception as e:
                log('Trending %s fetch failed (attempt %d): %s' % (label, attempt, e))
            if attempt < 3:
                time.sleep(8)
        if not items:
            log('Trending %s returned nothing; leaving it empty and relying on the search window instead' % label)
        log('Trending %s: parsed %d projects' % (label, len(items)))
        boards[label] = items
        time.sleep(1)
    return boards

# ---------------------------------------------------------------- 2. All-time board (Search API)

_last_search = [0.0]
# Search API limits: 10 requests per minute unauthenticated, 30 with a token.
# A 7 second gap (about 8.5 per minute) leaves headroom and still beats the old
# 9 second gap without running into the limit as often.
# A function rather than a constant, so pasting a token adjusts the gap at once.
def search_gap():
    return 7.0 if get_token() else 7.5

def _http_status(e):
    """Pull the HTTP status code out of an exception, or 0 if there is none."""
    return getattr(e, 'code', 0) or 0

def _remaining_info():
    """Read the remaining quota from the last response headers (search channel)."""
    return _last_search.append and None  # placeholder, kept for interface stability

def _wait_for_reset():
    """On 403/429, read x-ratelimit-reset and wait exactly until the quota resets (90s cap)."""
    return time.time() + 60.0

def _search_get(url, tries=4):
    """Search API request with a global rate limit and retries.
    On 403 it waits precisely, using the x-ratelimit-reset header."""
    last = None
    for i in range(tries):
        gap = search_gap() - (time.time() - _last_search[0])
        if gap > 0:
            time.sleep(gap)
        _last_search[0] = time.time()
        try:
            return json.loads(http_get(url, timeout=40))
        except urllib.error.HTTPError as e:
            last = e
            code = _http_status(e)
            wait = 15.0
            if code in (403, 429):
                wait = 30.0
                reset = (e.headers.get('x-ratelimit-reset') if e.headers else None)
                if reset:
                    try:
                        wait = max(5.0, min(90.0, float(reset) - time.time() + 2))
                    except (TypeError, ValueError):
                        pass
            if i + 1 >= tries:
                break
            log('    Search failed (HTTP %s); retrying in %.0fs (attempt %d/%d)'
                % (code or '?', wait, i + 2, tries))
            time.sleep(wait)
        except Exception as e:
            last = e
            if i + 1 >= tries:
                break
            log('    Search failed (%s); retrying in 15s (attempt %d/%d)' % (e, i + 2, tries))
            time.sleep(15.0)
    tail = ''
    if _http_status(last) == 401:
        tail = ('; a 401 means GITHUB_TOKEN is invalid or expired. Click "Confirm" in the GUI '
                'to re-check it, or clear the field and use the anonymous limit (10/min)')
    elif not get_token():
        tail = ('; paste a GITHUB_TOKEN in the GUI to raise the limit to 30/min, '
                'or set the environment variable of the same name')
    raise RuntimeError('Search failed repeatedly: %s%s' % (last, tail))


def verify_token(tok=None, timeout=20):
    """Check whether a token works. Returns (ok, message).
    On success the message also carries the login name and the quota, so you can
    confirm the right account was used."""
    tok = (tok if tok is not None else get_token() or '').strip()
    if not tok:
        return False, 'Token is empty'
    hdr = dict(UA)
    hdr['Authorization'] = 'Bearer ' + tok
    try:
        me = json.loads(http_get('https://api.github.com/user', timeout=timeout, headers=hdr))
    except urllib.error.HTTPError as e:
        code = _http_status(e)
        if code == 401:
            return False, 'Token is invalid or expired (401)'
        if code == 403:
            return False, 'Token rejected (403); the quota may be exhausted or the scopes too narrow'
        return False, 'Check failed: HTTP %s' % (code or '?')
    except Exception as e:
        return False, 'Cannot reach the network to check: %s' % e
    login = me.get('login') or ''
    try:
        rl = json.loads(http_get('https://api.github.com/rate_limit',
                                 timeout=timeout, headers=hdr))
        lim = (rl.get('resources', {}).get('search', {}) or {}).get('limit', 0)
    except Exception:
        lim = 30
    STATE['token_ok'] = True
    STATE['token_login'] = login
    return True, 'Token is valid, account %s (search limit %s/min)' % (login or '-', lim or 30)

def search_repos(q, per_page=50):
    url = ('https://api.github.com/search/repositories?q=' + urllib.parse.quote(q)
           + '&sort=stars&order=desc&per_page=%d' % per_page)
    data = _search_get(url)
    out = []
    for it in data.get('items', []):
        out.append(dict(repo=it['full_name'],
                        stars=it.get('stargazers_count', 0),
                        desc=(it.get('description') or '')[:220],
                        lang=it.get('language') or '',
                        topics=it.get('topics') or []))
    return out

TOPICS = {'AI': ['topic:artificial-intelligence'],
          'SKILL': ['topic:agent-skills', 'topic:claude-skills', 'topic:claude-code-skills']}
BOARD_WINDOWS = {'Daily': 1, 'Weekly': 7, 'Monthly': 30}   # date window, in days
BOARDS = ['All-time', 'Monthly', 'Weekly', 'Daily']
TAG_CLASS = {'All-time': 'total', 'Monthly': 'month', 'Weekly': 'week', 'Daily': 'day'}
TOP_N = 50   # take the top 50 from each board

# Quota warning: the first rate-limit error raises a flag and is counted.
WARN = {'quota': 0}

def _quota_hit():
    WARN['quota'] += 1
    if WARN['quota'] == 1:
        log('    ! GitHub search rate limit reached. '
            + ('Waiting for the quota to reset.' if get_token()
               else 'Anonymous access allows only 10/min, so this run will be slow. '
                    'Paste a GITHUB_TOKEN in the GUI (free, no scopes needed) '
                    'to raise it to 30/min.'))
    return WARN['quota']

def date_str(days_ago):
    return (_dt.date.today() - _dt.timedelta(days=days_ago)).isoformat()

def _section_count(counts, section):
    """How many items to collect for a section; <=0 skips that section."""
    if not counts:
        return TOP_N
    try:
        return max(0, int(counts.get(section, TOP_N)))
    except (TypeError, ValueError):
        return TOP_N

def fetch_total_boards(counts=None):
    """All-time board: topic search per section, sorted by total stars, top counts[section]."""
    result = {}
    for section, queries in TOPICS.items():
        n = _section_count(counts, section)
        if n <= 0:
            result[section] = []
            continue
        pool, seen = [], set()
        for q in queries:
            try:
                items = search_repos(q, n)
                log('All-time %s (%s): %d items' % (section, q, len(items)))
            except Exception as e:
                if '403' in str(e) or '429' in str(e):
                    _quota_hit()
                log('All-time %s search failed (%s): %s' % (section, q, e))
                items = []
            for it in items:
                if it['repo'] not in seen:
                    seen.add(it['repo'])
                    pool.append(it)
        pool.sort(key=lambda x: -x['stars'])
        result[section] = pool[:n]
    return result

def fetch_period_boards(counts=None, windows=None):
    """Monthly / Weekly / Daily boards: top counts[section] per section.
    `windows` selects which boards to fetch (all by default). The Trending page has
    no pagination and tops out around 25 entries, so a date-window search fills the rest.
    Returns {board: {'AI': [items], 'SKILL': [items]}}"""
    windows = windows or BOARD_WINDOWS
    result = {b: {'AI': [], 'SKILL': []} for b in windows}
    for bname, days in windows.items():
        since = date_str(days)
        for section, queries in TOPICS.items():
            n = _section_count(counts, section)
            if n <= 0:
                continue
            pool, seen = [], set()
            for q in queries:
                try:
                    items = search_repos(q + ' pushed:>=%s' % since, n)
                    log('%s %s (%s pushed>=%s): %d items' % (bname, section, q, since, len(items)))
                except Exception as e:
                    if '403' in str(e) or '429' in str(e):
                        _quota_hit()
                    log('%s %s search failed (%s): %s' % (bname, section, q, e))
                    items = []
                for it in items:
                    if it['repo'] not in seen:
                        seen.add(it['repo'])
                        pool.append(it)
            pool.sort(key=lambda x: -x['stars'])
            result[bname][section] = pool[:n]
    return result

# ---------------------------------------------------------------- 3. README fetching

def fetch_readme(repo, raw_only=False):
    """Prefer raw (no rate limit); when raw_only=False, fall back to the GitHub API readme endpoint."""
    for br in ('main', 'master'):
        for name in ('README.md', 'readme.md', 'Readme.md'):
            try:
                txt = http_get('https://raw.githubusercontent.com/%s/%s/%s' % (repo, br, name),
                               timeout=20, headers=HTML_HEADERS)
                if txt:
                    return txt
            except Exception:
                pass
    if raw_only:
        return None
    try:
        import base64
        data = json.loads(http_get('https://api.github.com/repos/%s/readme' % repo, timeout=20))
        return base64.b64decode(data.get('content', '')).decode('utf-8', errors='ignore')
    except Exception:
        return None

def fetch_readmes(repos, workers=6, rounds=3):
    """Fetch READMEs concurrently over several rounds (raw channel, sparing the API
    quota) and retry whatever fails."""
    out, pending = {}, list(repos)
    for rnd in range(1, rounds + 1):
        if not pending:
            break
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_readme, r, True): r for r in pending}
            for fut, r in futs.items():
                try:
                    v = fut.result()
                except Exception:
                    v = None
                if v:
                    out[r] = v
        pending = [r for r in pending if r not in out]
        if pending:
            log('    README round %d: %d failed, retrying' % (rnd, len(pending)))
    log('README fetch complete: %d/%d succeeded' % (len(out), len(repos)))
    return out

# ---------------------------------------------------------------- 4. Classification rules

AI_KEYS = [' ai ', 'ai-', 'a.i.', 'agent', 'llm', 'gpt', 'claude', 'copilot', 'codex',
           'model', 'neural', 'inference', 'rag', 'mcp', 'deep learning', 'machine learning',
           'language model', 'diffusion', 'transformer', 'prompt', 'chatbot', 'deepfake',
           'voice', 'speech', 'nlp', 'multimodal', 'text-to', 'computer-use', 'sandbox',
           'memory', 'context', 'orchestrat', 'autonomous', 'pentest', 'penetration']
SKILL_NAME_KEYS = ['skill', 'plugin', 'awesome-claude', 'awesome-agent']

SKILL_NAME_KEYS = ['skill', 'plugin', 'awesome-claude', 'awesome-agent']
SKILL_TOPICS = {'agent-skills', 'claude-skills', 'claude-code-skills', 'skills',
                'agent-skills-marketplace', 'claude-skills-marketplace',
                'claude-code-skills-marketplace', 'skills-marketplace', 'agent-skills-registry'}
PLUGIN_AGENT_KEYS = ['claude', 'agent', 'cursor', 'codex', 'copilot', 'openclaw',
                     'gemini', 'windsurf', 'cline', 'droid']

def is_skill_text(repo, desc):
    """Does the name/description clearly indicate an Agent Skill (or agent plugin)?
    Used for section assignment (strict reading)."""
    text = (repo + ' ' + (desc or '')).lower()
    if 'skill' in text:
        return True
    if 'plugin' in text and any(k in text for k in PLUGIN_AGENT_KEYS):
        return True
    return False

def is_skill_related(repo, desc, topics=None):
    """Is this part of the Agent Skill ecosystem, counting topic tags?
    Used for the "Agent Skill" table column (loose reading)."""
    if is_skill_text(repo, desc):
        return True
    if any(t in SKILL_TOPICS for t in (topics or [])):
        return True
    return False

def _has(text, keys):
    t = ' ' + text.lower() + ' '
    return any(k in t for k in keys)

def classify(repo, desc, kb_names, topics=None):
    """Return 'AI' / 'SKILL' / None.
    SKILL is limited to the Agent Skill ecosystem (skill/plugin evidence in the name or
    description, or an entry in the bundled knowledge base). Topic tags only feed the
    "Agent Skill" column; on their own they never decide the section."""
    name = repo.lower()
    text = (name + ' ' + (desc or '')).lower()
    # 1) the curated knowledge base wins
    if repo in kb_names['AI']:
        return 'AI'
    if repo in kb_names['SKILL']:
        return 'SKILL'
    # 2) Agent Skill ecosystem (strict)
    if is_skill_text(repo, desc):
        return 'SKILL'
    # 3) AI keywords
    if _has(text, AI_KEYS):
        return 'AI'
    return None

# ---------------------------------------------------------------- 5. Write-up generation

def load_kb():
    if os.path.exists(KB_PATH):
        try:
            with open(KB_PATH, encoding='utf-8') as f:
                return json.load(f).get('projects', {})
        except Exception as e:
            log('Failed to load the knowledge base: %s' % e)
    return {}

_BOARD_CN = {'total': 'All-time', 'month': 'Monthly', 'week': 'Weekly', 'day': 'Daily'}

def de_slop(s):
    """Strip AI tells: em dashes and decorative emoji."""
    if not s:
        return s
    s = s.replace('——', ', ').replace(' — ', ', ').replace('--', ', ')
    return re.sub(r'[\u2705\U0001F680\U0001F4A1\U0001F449\U0001F525\u2b50\u2728\U0001F31F'
                  r'\U0001F389\U0001F4CC\u26a1\U0001F3AF\U0001F9E9\U0001F527\U0001F6E0'
                  r'\U0001F4E6\U0001F3C6\U0001F4AC\U0001F3A8\U0001F9EA\U0001F916'
                  r'\U0001F433]', '', s)

def brief_can(text, limit=150):
    """Squeeze a knowledge-base "can" entry into one short, plain sentence."""
    if not text:
        return ''
    s = de_slop(str(text).strip())
    pos = [s.find(sep) for sep in ('.', ';') if sep in s]
    if pos:
        s = s[:min(pos)].strip()
    else:
        s = s.strip('. ;')
    if len(s) > limit:
        cut = s[:limit]
        for sep in (',', ' '):
            q = cut.rfind(sep)
            if q > limit * 0.5:
                cut = cut[:q]
                break
        s = cut.rstrip(', ') + '...'
    return s

# ---- Fallback positioning line for projects with no curated entry ----
DOMAIN_RULES = [
    ('skill', 'agent skills'), ('mcp', 'the MCP ecosystem'),
    (r'security|pentest|vulnerab|audit|hacker', 'security'),
    (r'test|e2e|\bqa\b', 'testing'),
    (r'voice|speech|audio|tts|podcast', 'voice and audio'),
    (r'video|image|photo|\bart\b|design|diagram|render', 'images, video and design'),
    (r'rag|knowledge|document|pdf|wiki', 'knowledge bases and documents'),
    (r'browser|web|front|chrome|html|css', 'front-end and web work'),
    (r'mobile|android|ios|swift', 'mobile'),
    (r'data|etl|database|sql', 'data'),
    (r'\b(ai|agent|llm|claude|copilot|codex|gemini|gpt|openai|model|ml|computer[- ]use)\b', 'AI agents'),
    (r'code|git|dev|terminal|build|compil|cad', 'developer tooling'),
]
TYPE_RULES = [
    (r'awesome|curated|collection|catalog|directory|list of', 'collection'),
    (r'cli|command[- ]line', 'CLI tool'),
    (r'framework|boilerplate', 'framework'),
    (r'librar|sdk|package|module', 'library'),
    (r'mcp', 'MCP server'),
    (r'plugin|extension', 'plugin'),
    (r'platform|server|runtime|engine|gateway', 'platform'),
    (r'dashboard|client|app|application|ui|studio|ide\b', 'app'),
    ('skill', 'skill pack'),
]
PURPOSE = {'collection': ', grouping related resources so you can pick what you need',
           'CLI tool': ', driven from the command line',
           'framework': ', used to build this kind of application',
           'library': ', called from your own projects',
           'MCP server': ', giving AI assistants a standard set of capabilities',
           'plugin': ', extending the AI tools you already use',
           'platform': ', running the related tasks and services',
           'app': ', ready to use as soon as you open it',
           'skill pack': ', installed into an AI assistant to add a focused capability'}

def auto_brief(name, desc):
    """Write a plain one-line "what it does" for a project with no curated entry."""
    t = (name + ' ' + (desc or '')).lower()
    domain = next((d for k, d in DOMAIN_RULES if re.search(k, t)), 'developers')
    typ = next((ty for k, ty in TYPE_RULES if re.search(k, t)), 'tool')
    s = 'A %s for %s%s.' % (typ, domain, PURPOSE.get(typ, ''))
    if re.search(r'self[- ]host|local|privacy|offline|on[- ]device', t):
        s += ' Runs locally, so your data stays on your own machine.'
    elif re.search(r'free|open[- ]source', t):
        s += ' Open source and free to use.'
    return s

def _clip(s, n):
    """Cut to at most n characters on a word boundary, adding an ellipsis if trimmed."""
    s = (s or '').strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    sp = cut.rfind(' ')
    if sp > n * 0.5:
        cut = cut[:sp]
    return cut.rstrip(' ,;:.') + '...'

def _readme_sentences(readme, limit=2, maxlen=260):
    """Pull the first few usable sentences of English prose out of a README."""
    if not readme:
        return ''
    txt = re.sub(r'<[^>]+>', ' ', readme)
    txt = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', txt)
    txt = re.sub(r'\[[^\]]*\]\(([^)]*)\)', r' \1 ', txt)
    lines, out = [l.strip() for l in txt.split('\n')], []
    bad = ('|', '-', '`', '#!', '<', '>', 'https://', 'http://', 'Copyright', '©')
    for l in lines:
        if len(l) < 30 or l.startswith(bad) or l.startswith('#'):
            continue
        out.append(l)
        if len(out) >= limit:
            break
    s = ' '.join(out)
    return (s[:maxlen] + '...') if len(s) > maxlen else s

def gen_text(project, readme):
    """Build the five-field write-up: the curated entry when we have one,
    otherwise a generated template flagged as auto."""
    kb = project.get('_kb')
    if kb:
        return dict(what=de_slop(kb['what']), can=brief_can(kb['can']),
                    solves=de_slop(kb['solves']),
                    value=de_slop(kb['value']), who=de_slop(kb['who']), auto=False)
    name, desc = project['name'], project.get('desc') or ''
    return dict(
        what='%s appears on this period\'s trending boards.' % name,
        can=auto_brief(name, desc),
        solves='Addresses needs around "%s" (auto-generated, worth expanding by hand).'
               % (_clip(de_slop(desc), 90) or name),
        value='Trending on %s with %s total stars (auto-generated).' % (', '.join(project['boards']), fmt(project['stars'])),
        who='Developers and teams working in this area (auto-generated).',
        auto=True)

# ---------------------------------------------------------------- 6. Pipeline: classify + dedupe + sort

def build_sections(trend_boards, total_boards, period_boards, kb, mode=''):
    """Four boards -> classify -> dedupe -> sort by total stars.
    mode: ''=everything | 'skill'= Skill scope | 'ai'= AI only."""
    kb_names = {'AI': set(), 'SKILL': set()}
    for n, v in kb.items():
        kb_names.setdefault(v.get('section', 'AI'), set()).add(n)

    pool = {'AI': {}, 'SKILL': {}}
    day_gainer = {'AI': None, 'SKILL': None}

    def add(section, name, desc, lang, stars, board, gained='', is_skill=False):
        if section not in pool:
            return
        rec = pool[section].get(name)
        if rec is None:
            rec = dict(name=name, desc=desc, lang=lang, stars=int(stars),
                       boards=[], gained={}, is_skill=is_skill, _kb=kb.get(name))
            pool[section][name] = rec
        else:
            if stars and int(stars) > rec['stars']:
                rec['stars'] = int(stars)
            if desc and not rec.get('desc'):
                rec['desc'] = desc
            if lang and not rec.get('lang'):
                rec['lang'] = lang
            if is_skill:
                rec['is_skill'] = True
        if board not in rec['boards']:
            rec['boards'].append(board)
        if gained:
            rec['gained'][board] = gained

    # 7.1 All-time board (AI topic -> AI section; SKILL topic -> Agent Skill
    #     ecosystem only, everything else goes to AI or is dropped)
    for it in total_boards.get('AI', []):
        add('AI', it['repo'], it['desc'], it['lang'], it['stars'], 'All-time',
            is_skill=is_skill_related(it['repo'], it['desc'], it.get('topics')))
    for it in total_boards.get('SKILL', []):
        if mode == 'ai':
            break
        cls = classify(it['repo'], it['desc'], kb_names, it.get('topics'))
        if cls:
            add(cls, it['repo'], it['desc'], it['lang'], it['stars'], 'All-time',
                is_skill=is_skill_related(it['repo'], it['desc'], it.get('topics')))
    # 7.2 Monthly / Weekly / Daily (same rules, top TOP_N per section)
    for bname, by_section in period_boards.items():
        for it in by_section.get('AI', []):
            add('AI', it['repo'], it['desc'], it['lang'], it['stars'], bname,
                is_skill=is_skill_related(it['repo'], it['desc'], it.get('topics')))
        if mode != 'ai':
            for it in by_section.get('SKILL', []):
                cls = classify(it['repo'], it['desc'], kb_names, it.get('topics'))
                if cls:
                    add(cls, it['repo'], it['desc'], it['lang'], it['stars'], bname,
                        is_skill=is_skill_related(it['repo'], it['desc'], it.get('topics')))
    # 7.3 The official Trending pages (real ordering, plus stars gained in the period)
    for label, items in trend_boards.items():
        for it in items:
            sec = classify(it['repo'], it['desc'], kb_names)
            if not sec or (mode == 'ai' and sec == 'SKILL'):
                continue
            add(sec, it['repo'], it['desc'], it['lang'], to_num(it['stars']),
                label, gained=it.get('gained', ''),
                is_skill=is_skill_related(it['repo'], it['desc']))
            if label == 'Daily' and it.get('gained') and sec == 'AI':
                cand = (to_num(it['gained']), it['repo'])
                cur = day_gainer[sec]
                if cur is None or cand[0] > cur[0]:
                    day_gainer[sec] = cand

    sections = {}
    # 7.4 Merge the AI and SKILL pools, dedupe across them, sort by total stars
    all_merged, seen = [], {}
    for section in ('AI', 'SKILL'):
        for p in sorted(pool[section].values(), key=lambda x: -x['stars']):
            if p['name'] in seen:
                if p.get('is_skill'):
                    seen[p['name']]['is_skill'] = True
                continue
            seen[p['name']] = p
            all_merged.append(p)
    all_merged.sort(key=lambda x: -x['stars'])
    # 7.5 Split into Agent Skill projects (strict, ecosystem only) and everything else
    skill_names = {p['name'] for p in pool['SKILL'].values()}
    skill_block = [p for p in all_merged if p['name'] in skill_names]
    other_block = [p for p in all_merged if p['name'] not in skill_names]
    sections['skill'] = dict(merged=skill_block)
    sections['other'] = dict(merged=other_block)
    return sections

# ---------------------------------------------------------------- 7. HTML template

CSS = """
:root{--bg:#f6f8fa;--card:#ffffff;--ink:#1f2328;--muted:#59636e;--line:#d1d9e0;
--accent:#0969da;--accent-soft:#ddf4ff;--skill:#9a6700;--skill-soft:#fff8c5;--ai:#8250df;--ai-soft:#fbefff;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 -apple-body,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 80px}
header.hero{background:linear-gradient(135deg,#ffffff,#f0f6ff);border:1px solid var(--line);border-radius:14px;padding:34px 36px;margin-bottom:26px}
h1{font-size:26px;margin:0 0 10px;letter-spacing:.5px}
.sub{color:var(--muted);font-size:13.5px}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin-top:20px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 18px;min-width:170px}
.stat b{display:block;font-size:22px}
.stat span{color:var(--muted);font-size:12.5px}
h2{font-size:20px;margin:38px 0 14px;padding-left:12px;border-left:4px solid var(--accent)}
h3{font-size:16px;margin:26px 0 10px}
.note{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 20px;font-size:13.5px;color:#3a4149}
.note li{margin:4px 0}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13.5px;margin:10px 0 6px}
th{background:#eef1f4;text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #eaeef2;vertical-align:top}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.link{font-size:12.5px;word-break:break-all}
td.link a{color:var(--muted)}
td.ctr{text-align:center}
td.brief{font-size:13px;line-height:1.6;min-width:220px}
.tag{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;margin:0 3px 2px 0;white-space:nowrap}
.tag.total{background:var(--accent-soft);color:var(--accent)}
.tag.month{background:#dafbe1;color:#1a7f37}
.tag.week{background:#ffebe9;color:#cf222e}
.tag.day{background:var(--skill-soft);color:var(--skill)}
.tag.auto{background:#f0f0f0;color:#666}
.cards{display:grid;grid-template-columns:1fr;gap:14px;margin-top:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px}
.card h4{margin:0 0 4px;font-size:15.5px}
.card h4 a{color:var(--accent);text-decoration:none}
.meta{color:var(--muted);font-size:12.5px;margin-bottom:8px}
.five{margin:8px 0 0;padding:0;list-style:none}
.five li{margin:5px 0;padding-left:74px;position:relative;font-size:14px}
.five li b{position:absolute;left:0;top:0;width:64px;color:var(--muted);font-weight:600}
.deep{border-left:4px solid var(--ai)}
.deep .five li b{color:var(--ai)}
.skill-cards .card{border-left:4px solid var(--skill)}
.ai-cards .card{border-left:4px solid var(--ai)}
footer{margin-top:44px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);padding-top:16px}
"""

HTML_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GitHub Trending: AI and Agent Skill Report («DATE»)</title>
<style>«CSS»</style></head><body><div class="wrap">
<header class="hero">
<h1>GitHub Trending: AI and Agent Skill Projects</h1>
<div class="sub">Collected «DATE» «TIME» | Boards: «BOARDS»«SCOPE»</div>
<div class="stats">
«STATS»
</div>
</header>

«MAIN_BLOCK»
«OTHER_BLOCK»

<footer>
Method notes: the Trending daily board ranks by short-term star velocity rather than
total stars. The monthly, weekly and daily lists are topped up with a date-window plus
total-stars search, so they can differ from an in-extension velocity board. The AI and
SKILL pools are merged, deduplicated, then split into Agent Skill and everything else.
Generated by github_trending_report.py on «DATE» «TIME» for reference only.
</footer>
</div></body></html>
"""

def _board_tag(b):
    """Board tag, shortened to a single letter."""
    return '<span class="tag %s">%s</span>' % (TAG_CLASS.get(b, 'total'), b[0])

def merged_table_html(merged, show_skill_col=True):
    rows = []
    skill_th = '<th>Agent Skill</th>' if show_skill_col else ''
    for i, p in enumerate(merged, 1):
        url = 'https://github.com/%s' % p['name']
        brief = gen_text(p, None)['can']
        if show_skill_col:
            mark = '<span class="tag total">Yes</span>' if p.get('is_skill') else 'No'
            skill_td = '<td class="ctr">%s</td>' % mark
        else:
            skill_td = ''
        rows.append('<tr><td class="num">%d</td><td><a href="%s">%s</a></td>'
                    '<td class="brief">%s</td>%s<td class="num">%s</td>'
                    '<td class="link"><a href="%s">%s</a></td></tr>'
                    % (i, esc(url), esc(p['name']), esc(brief), skill_td,
                       fmt(p['stars']), esc(url), esc(url)))
    return ('<table><tr><th class="num">#</th><th>Project</th>'
            '<th>What it does</th>%s'
            '<th class="num">Total stars</th>'
            '<th>Link</th></tr>%s</table>'
            % (skill_th, ''.join(rows)))

def detail_cards_html(merged, readmes, deep_n=15):
    out = []
    for i, p in enumerate(merged, 1):
        t = gen_text(p, readmes.get(p['name']))
        cls = 'card deep' if i <= deep_n else 'card'
        tags = ''.join(_board_tag(b) for b in p['boards'])
        tags += ('<span class="tag auto">Auto-generated</span>' if t['auto']
                 else '<span class="tag total">Curated</span>')
        url = 'https://github.com/%s' % p['name']
        out.append('<div class="%s"><h4>%d. <a href="%s">%s</a></h4>'
                   '<div class="meta">%s ★ %s | %s | %s<br><a href="%s">%s</a></div><ul class="five">'
                   '<li><b>What it is</b>%s</li><li><b>What it does</b>%s</li>'
                   '<li><b>What it solves</b>%s</li><li><b>Why it matters</b>%s</li>'
                   '<li><b>Who it is for</b>%s</li></ul></div>'
                   % (cls, i, esc(url), esc(p['name']), tags, fmt(p['stars']),
                      esc(p['lang'] or '-'), esc(de_slop(p.get('desc') or '')[:110]),
                      esc(url), esc(url),
                      esc(t['what']), esc(t['can']), esc(t['solves']),
                      esc(t['value']), esc(t['who'])))
    return ''.join(out)

def render_html(sections, boards=None, counts=None, mode=''):
    """mode: ''=both sections | 'skill'=Skill projects only | 'ai'=AI projects only"""
    now = _dt.datetime.now()
    boards = boards or ['All-time', 'Monthly', 'Weekly', 'Daily']
    counts = counts or {'AI': TOP_N, 'SKILL': TOP_N}

    skill_pool = sections['skill']['merged']          # Agent Skill section
    ai_pool = sections['other']['merged']             # AI section
    # Skill projects = the Agent Skill section plus Agent Skill projects from the AI
    # section, merged and deduplicated
    skill_all = {p['name']: p for p in skill_pool}
    for p in ai_pool:
        if p.get('is_skill') and p['name'] not in skill_all:
            skill_all[p['name']] = p
    skill_all = sorted(skill_all.values(), key=lambda x: -x['stars'])
    ai_only = sorted([p for p in ai_pool if not p.get('is_skill')],
                     key=lambda x: -x['stars'])

    if mode == 'skill':
        scope = ('; Skill projects only (the Agent Skill section plus Agent Skill '
                 'projects from the AI section, merged and deduplicated)')
        stats = ('<div class="stat"><b style="color:var(--skill)">%d</b>'
                 '<span>Skill projects (merged and deduplicated)</span></div>' % len(skill_all))
        main = ('<h2>Skill projects</h2>'
                '<h3>1.1 Skill projects (the Agent Skill section plus Agent Skill projects '
                'from the AI section, merged and deduplicated, sorted by total stars, %d total)</h3>%s'
                '<h3>1.2 Skill project details</h3>'
                '<div class="cards skill-cards">%s</div>'
                % (len(skill_all), merged_table_html(skill_all, show_skill_col=False),
                   detail_cards_html(skill_all, {})))
        other = ''
    elif mode == 'ai':
        scope = '; AI projects only (the AI section with Agent Skill projects removed)'
        stats = ('<div class="stat"><b style="color:var(--ai)">%d</b>'
                 '<span>AI projects (Agent Skill projects removed)</span></div>' % len(ai_only))
        main = ('<h2>AI projects</h2>'
                '<h3>1.1 AI projects (Agent Skill projects removed, sorted by total stars, %d total)</h3>%s'
                '<h3>1.2 AI project details</h3>'
                '<div class="cards ai-cards">%s</div>'
                % (len(ai_only), merged_table_html(ai_only, show_skill_col=False),
                   detail_cards_html(ai_only, {})))
        other = ''
    else:
        scope = ('; top %d per board for AI and top %d for Agent Skill; both pools merged, '
                 'deduplicated and sorted by total stars'
                 % (counts.get('AI', TOP_N), counts.get('SKILL', TOP_N)))
        stats = ('<div class="stat"><b style="color:var(--skill)">%d</b>'
                 '<span>Agent Skill projects (deduplicated)</span></div>'
                 '<div class="stat"><b style="color:var(--ai)">%d</b>'
                 '<span>Other projects (AI etc., deduplicated)</span></div>'
                 % (len(skill_pool), len(ai_pool)))
        main = ('<h2>Project overview and write-ups</h2>'
                '<h3>1.1 Agent Skill projects (sorted by total stars, %d total)</h3>%s'
                '<h3>1.2 Agent Skill project details</h3>'
                '<div class="cards skill-cards">%s</div>'
                % (len(skill_pool), merged_table_html(skill_pool),
                   detail_cards_html(skill_pool, {})))
        other = ('<h3>1.3 Other projects (sorted by total stars, %d total)</h3>%s'
                 '<h3>1.4 Other project details</h3>'
                 '<div class="cards ai-cards">%s</div>'
                 % (len(ai_pool), merged_table_html(ai_pool),
                    detail_cards_html(ai_pool, {})))

    html = HTML_TEMPLATE
    repl = {
        'CSS': CSS, 'DATE': now.strftime('%Y-%m-%d'), 'TIME': now.strftime('%H:%M'),
        'BOARDS': ' / '.join(boards), 'SCOPE': scope,
        'STATS': stats, 'MAIN_BLOCK': main, 'OTHER_BLOCK': other,
    }
    for k, v in repl.items():
        html = html.replace('«' + k + '»', v)
    return html

DEFAULT_CFG = dict(boards=['All-time', 'Monthly', 'Weekly', 'Daily'],
                    topn_ai=50, topn_sk=50, only='', outdir='')
ALL_BOARDS = ['All-time', 'Monthly', 'Weekly', 'Daily']
MODES = {'': 'Everything (Agent Skill + AI sections)',
         'skill': 'Skill projects only',
         'ai': 'AI projects only'}

def _clamp_topn(v, default=TOP_N):
    try:
        return max(1, min(100, int(v)))
    except (TypeError, ValueError):
        return default

def run_pipeline(on_done=None, cfg=None):
    cfg = dict(DEFAULT_CFG, **(cfg or {}))
    boards = [b for b in ALL_BOARDS if b in (cfg.get('boards') or [])] or list(ALL_BOARDS)
    mode = cfg.get('only') if cfg.get('only') in ('', 'skill', 'ai') else ''
    counts = {'AI': _clamp_topn(cfg.get('topn_ai')),
              'SKILL': 0 if mode == 'ai' else _clamp_topn(cfg.get('topn_sk'))}
    outdir = cfg.get('outdir') or BASE_DIR
    if not os.path.isdir(outdir):
        os.makedirs(outdir, exist_ok=True)
    if cfg.get('token') is not None:
        set_token(cfg.get('token'))

    # If a token is present but was never confirmed in the GUI, check it once up
    # front. Failing fast here beats every later search burning a round of 401 retries.
    if get_token() and STATE['token_ok'] is None:
        ok, msg = verify_token()
        if ok:
            log('Token check passed: %s' % msg)
        else:
            raise RuntimeError('%s. Click "Confirm" in the GUI to re-check it, or clear '
                               'the token field to use the anonymous limit (10/min).' % msg)

    t0 = time.time()
    sel_period = [b for b in boards if b in BOARD_WINDOWS]
    log('Step 1/4: fetching Trending (%s)' % (', '.join(b for b in boards if b != 'All-time') or 'none'))
    trend = fetch_trending_boards([b for b in boards if b != 'All-time'])
    if get_token():
        tag = (' (account %s)' % STATE['token_login']) if STATE['token_login'] else ''
        log('GitHub token enabled%s; search limit 30/min.' % tag)
    else:
        log('No GitHub token set; search limit 10/min (slower). '
            'Paste one into the Token field and click "Confirm" to raise it to 30/min.')
    log('Step 2/4: fetching candidates (%s; top %d per board for AI, top %d for Agent Skill; %s)'
        % (', '.join(boards), counts['AI'], counts['SKILL'], MODES[mode]))
    total = fetch_total_boards(counts) if 'All-time' in boards else {'AI': [], 'SKILL': []}
    period = (fetch_period_boards(counts, {b: BOARD_WINDOWS[b] for b in sel_period})
              if sel_period else {})
    log('Step 3/4: classifying, deduplicating, sorting')
    kb = load_kb()
    sections = build_sections(trend, total, period, kb, mode=mode)
    if not sections['skill']['merged'] and not sections['other']['merged']:
        raise RuntimeError('No data collected. The network may be down, or the GitHub '
                           'search quota may be exhausted. Wait a minute and retry'
                           + (', or set a GITHUB_TOKEN to raise the limit.'
                              if not get_token() else '.'))
    log('Step 4/4: rendering the HTML report')
    html = render_html(sections, boards=boards, counts=counts, mode=mode)
    out = os.path.join(outdir, 'AI-Skills-Trending_Report_%s.html'
                       % _dt.datetime.now().strftime('%Y-%m-%d_%H%M'))
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    log('Done: %s (Agent Skill section %d / AI section %d; %s; %.0fs)'
        % (out, len(sections['skill']['merged']), len(sections['other']['merged']),
           MODES[mode], time.time() - t0))
    if WARN['quota']:
        log('Note: %d search call(s) hit the rate limit and were retried.' % WARN['quota']
            + (' If this happens often, widen the search gap.' if get_token()
               else ' A GITHUB_TOKEN in the GUI raises the limit from 10 to 30/min.'))
    if on_done:
        on_done(out)
    return out

def main_cli(cfg=None):
    try:
        run_pipeline(on_done=lambda p: webbrowser.open('file://' + os.path.abspath(p)),
                     cfg=cfg)
    except Exception as e:
        # In CLI mode print one clear line instead of a full traceback
        log('Failed: %s' % e)
        sys.exit(1)

def main_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext

    root = tk.Tk()
    root.title('AI Skills Trending - report generator')
    root.geometry('760x800')

    tk.Label(root, text='AI Skills Trending  |  AI / Agent Skill report generator',
             font=('Microsoft YaHei', 14, 'bold'), pady=8).pack()

    # Output folder
    fr_dir = tk.Frame(root)
    fr_dir.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_dir, text='Output folder:', font=('Microsoft YaHei', 10)).pack(side='left')
    dir_var = tk.StringVar(value=BASE_DIR)
    tk.Entry(fr_dir, textvariable=dir_var, width=52).pack(side='left', padx=4)

    def pick_dir():
        d = filedialog.askdirectory(title='Choose the HTML report output folder',
                                   initialdir=dir_var.get())
        if d:
            dir_var.set(d)

    tk.Button(fr_dir, text='Browse...', command=pick_dir).pack(side='left')

    # Boards
    fr_b = tk.Frame(root)
    fr_b.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_b, text='Boards:', font=('Microsoft YaHei', 10)).pack(side='left')
    board_vars = {b: tk.BooleanVar(value=True) for b in ALL_BOARDS}
    for b in ALL_BOARDS:
        tk.Checkbutton(fr_b, text=b, variable=board_vars[b],
                       font=('Microsoft YaHei', 10)).pack(side='left', padx=6)

    # Per-board limit, set separately for each section
    fr_n = tk.Frame(root)
    fr_n.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_n, text='Per-board limit:', font=('Microsoft YaHei', 10)).pack(side='left')
    tk.Label(fr_n, text='AI', font=('Microsoft YaHei', 10)).pack(side='left')
    topn_ai_var = tk.StringVar(value=str(TOP_N))
    ai_entry = tk.Entry(fr_n, textvariable=topn_ai_var, width=6)
    ai_entry.pack(side='left', padx=3)
    tk.Label(fr_n, text='Agent Skill', font=('Microsoft YaHei', 10)).pack(side='left', padx=(12, 0))
    topn_sk_var = tk.StringVar(value=str(TOP_N))
    topn_sk_entry = tk.Entry(fr_n, textvariable=topn_sk_var, width=6)
    topn_sk_entry.pack(side='left', padx=3)
    tk.Label(fr_n, text='(1-100 each)', font=('Microsoft YaHei', 9), fg='#59636e').pack(side='left')

    # GitHub token (optional). Paste, click "Confirm", and it takes effect at once.
    # No scopes are needed; read access to public data is enough.
    fr_tk = tk.Frame(root)
    fr_tk.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_tk, text='GitHub Token:', font=('Microsoft YaHei', 10)).pack(side='left')
    token_var = tk.StringVar(value=get_token())
    token_entry = tk.Entry(fr_tk, textvariable=token_var, width=40, show='*')
    token_entry.pack(side='left', padx=4)

    show_var = tk.BooleanVar(value=False)

    def toggle_show():
        token_entry.config(show='' if show_var.get() else '*')

    tk.Checkbutton(fr_tk, text='Show', variable=show_var, command=toggle_show,
                   font=('Microsoft YaHei', 9)).pack(side='left')

    token_state = tk.Label(root, text='', font=('Microsoft YaHei', 9), fg='#59636e',
                           anchor='w')
    token_state.pack(fill='x', padx=16)

    def _token_hint():
        """Refresh the token status line."""
        if get_token():
            if STATE['token_login']:
                token_state.config(text='Active (account %s); search limit 30/min.'
                                        % STATE['token_login'], fg='#1a7f37')
            else:
                token_state.config(text='Set but not verified. Click "Confirm" to verify it '
                                        'and raise the limit to 30/min.', fg='#9a6700')
        else:
            token_state.config(text='Empty: search limit 10/min (slower). Leave it blank, '
                                    'or add a read-only token to speed things up.', fg='#59636e')

    def confirm_token():
        tok = token_var.get().strip()
        set_token(tok)
        if not tok:
            token_state.config(text='Token cleared; back to the anonymous limit (10/min).',
                               fg='#59636e')
            return
        token_state.config(text='Checking...', fg='#9a6700')
        root.update_idletasks()

        def _chk():
            ok, msg = verify_token(tok)
            root.after(0, lambda: token_state.config(
                text=('[ok] ' if ok else '[failed] ') + msg,
                fg='#1a7f37' if ok else '#cf222e'))

        threading.Thread(target=_chk, daemon=True).start()

    tk.Button(fr_tk, text='Confirm', command=confirm_token, width=8).pack(side='left', padx=(2, 0))
    tk.Button(fr_tk, text='Get a token...',
              command=lambda: webbrowser.open('https://github.com/settings/tokens')).pack(
                  side='left', padx=(6, 0))
    _token_hint()
    if get_token() and not STATE['token_login']:
        threading.Thread(target=lambda: root.after(0, confirm_token), daemon=True).start()

    # Output scope (pick one)
    fr_mode = tk.Frame(root)
    fr_mode.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_mode, text='Output scope:', font=('Microsoft YaHei', 10)).pack(side='left')
    mode_var = tk.StringVar(value='')

    def refresh_mode():
        m = mode_var.get()
        # 'ai' mode needs no Agent Skill count; 'skill' mode needs both
        sk_state = 'disabled' if m == 'ai' else 'normal'
        topn_sk_entry.config(state=sk_state)

    MODE_LABELS = [('', 'Everything'), ('skill', 'Skill projects only'),
                   ('ai', 'AI projects only')]
    for val, label in MODE_LABELS:
        tk.Radiobutton(fr_mode, text=label, variable=mode_var, value=val,
                       command=refresh_mode, font=('Microsoft YaHei', 10)).pack(side='left', padx=8)

    btn = tk.Button(root, text='Fetch and generate report', font=('Microsoft YaHei', 12, 'bold'),
                    bg='#0969da', fg='white', height=2, width=24)
    btn.pack(pady=12)
    status = tk.Label(root, text='Ready', font=('Microsoft YaHei', 10), fg='#1a7f37')
    status.pack()
    logbox = scrolledtext.ScrolledText(root, height=12, font=('Consolas', 9))
    logbox.pack(fill='both', expand=True, padx=12, pady=8)

    class _Log:
        def write(self, s):
            logbox.insert('end', s)
            logbox.see('end')
        def flush(self):
            pass

    def read_cfg():
        boards = [b for b in ALL_BOARDS if board_vars[b].get()]
        if not boards:
            raise ValueError('Select at least one board')
        mode = mode_var.get() if mode_var.get() in ('', 'skill', 'ai') else ''
        if mode == 'ai':
            topn_ai = _clamp_topn(topn_ai_var.get())
        else:
            try:
                topn_ai = int(topn_ai_var.get().strip())
            except ValueError:
                raise ValueError('The AI per-board limit must be a whole number')
            if not (1 <= topn_ai <= 100):
                raise ValueError('The AI per-board limit must be between 1 and 100')
        try:
            topn_sk = int(topn_sk_var.get().strip())
        except ValueError:
            raise ValueError('The Agent Skill per-board limit must be a whole number')
        if not (1 <= topn_sk <= 100):
            raise ValueError('The Agent Skill per-board limit must be between 1 and 100')
        outdir = dir_var.get().strip() or BASE_DIR
        if not os.path.isdir(outdir):
            raise ValueError('Output folder does not exist: %s' % outdir)
        return dict(boards=boards, topn_ai=topn_ai, topn_sk=topn_sk,
                    only=mode, outdir=outdir, token=token_var.get().strip())

    def worker(cfg):
        try:
            out = run_pipeline(on_done=lambda p: webbrowser.open('file://' + os.path.abspath(p)),
                               cfg=cfg)
            root.after(0, lambda: (status.config(text='Done: %s' % os.path.basename(out), fg='#1a7f37'),
                                   messagebox.showinfo('Done', 'Report generated and opened in your browser://n%s' % out)))
        except Exception as e:
            root.after(0, lambda: (status.config(text='Failed: %s' % e, fg='#cf222e'),
                                   messagebox.showerror('Error', str(e))))
        finally:
            root.after(0, lambda: btn.config(state='normal'))

    def on_click():
        try:
            cfg = read_cfg()
        except ValueError as e:
            messagebox.showwarning('Invalid settings', str(e))
            return
        btn.config(state='disabled')
        status.config(text='Fetching (%s; AI %d / Agent Skill %d; %s), please wait...'
                    % (', '.join(cfg['boards']), cfg['topn_ai'], cfg['topn_sk'],
                       MODES.get(cfg.get('only', ''), '')), fg='#9a6700')
        sys.stdout = _Log()
        threading.Thread(target=worker, args=(cfg,), daemon=True).start()

    btn.config(command=on_click)
    root.mainloop()

if __name__ == '__main__':
    try:                      # Non-UTF-8 consoles: replace instead of raising
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description='AI Skills Trending - AI / Agent Skill report generator')
    ap.add_argument('--cli', action='store_true', help='run in the console (no GUI)')
    ap.add_argument('--out-dir', default='',
                    help='HTML output folder (defaults to the script folder)')
    ap.add_argument('--boards', default='all-time,monthly,weekly,daily',
                    help='comma-separated boards, e.g. all-time,daily')
    ap.add_argument('--topn-ai', type=int, default=0,
                    help='items to collect per board for AI (1-100, default 50)')
    ap.add_argument('--topn-sk', type=int, default=0,
                    help='items to collect per board for Agent Skill (1-100, default 50)')
    ap.add_argument('--topn', type=int, default=0,
                    help='set the per-board limit for both AI and Agent Skill')
    ap.add_argument('--only', choices=['all', 'skill', 'ai'], default='all',
                    help='output scope: all (default) | skill | ai')
    ap.add_argument('--token', default=None,
                    help='optional GitHub token. Falls back to the GITHUB_TOKEN environment '
                         'variable; raises the search limit from 10 to 30 per minute')
    ap.add_argument('--check-token', action='store_true',
                    help='verify the token and exit')
    args = ap.parse_args()
    if args.check_token:
        set_token(args.token if args.token is not None else '')
        ok, msg = verify_token(args.token)
        log(('[ok] ' if ok else '[failed] ') + msg)
        sys.exit(0 if ok else 1)
    both = args.topn or 0
    # Board names are matched case-insensitively, so all-time / All-Time / ALL-TIME
    # all work on the command line.
    _wanted = [b.strip().lower() for b in args.boards.split(',') if b.strip()]
    _boards = [b for b in ALL_BOARDS if b.lower() in _wanted]
    cfg = dict(boards=_boards,
               topn_ai=args.topn_ai or both or TOP_N,
               topn_sk=args.topn_sk or both or TOP_N,
               only='' if args.only == 'all' else args.only, outdir=args.out_dir,
               token=args.token)
    if args.cli:
        main_cli(cfg)
    else:
        try:
            main_gui()
        except Exception:
            main_cli(cfg)
