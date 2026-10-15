#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub 热门榜 AI / SKILL 双版块报告一键生成器
================================================
一键完成：
  1) 实时拉取 GitHub 官方 Trending 日榜 / 周榜 / 月榜
  2) 按版块分别拉取总榜 / 月榜 / 周榜 / 日榜前 50 名
     （总榜：GitHub Search 按总星排序；月/周/日榜：同话题 + 时间窗检索补足）
  3) 按 AI / SKILL 版块分类、跨榜去重、按总星排序
  4) 生成与人工整理版同式同构的 HTML 报告（只呈现去重后项目，每个项目附链接；
     内置人工解读知识库，新上榜项目自动生成机读解读并标注）
用法：
  - 双击运行 / 无参数运行：打开图形界面。可手动选择输出目录、勾选总榜/月榜/周榜/日榜、
    分别输入 AI 与 Agent Skill 每榜搜集数量（1-100）、选择输出范围（全部 / 只输出 Skill 项目 /
    只输出 AI 项目），然后点击「一键拉取并生成报告」。
  - 命令行：python github_trending_report.py --cli [--out-dir 目录]
            [--boards 总榜,月榜,周榜,日榜] [--topn-ai 50] [--topn-sk 50]
            [--only all|skill|ai]（all=全部；skill=只输出 Skill 项目；
             ai=只输出 AI 项目）
依赖：仅 Python 3 标准库（无需 pip 安装任何东西）。
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
    """读取 GitHub Token（可选）：依次查环境变量 GITHUB_TOKEN / GH_TOKEN。
    配了 token 后 Search API 限额从 10 次/分钟升到 30 次/分钟，大幅减少等待。"""
    for k in ('GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_API_TOKEN'):
        v = (os.environ.get(k) or '').strip()
        if v:
            return v
    return ''

# Token 运行期可变：GUI 上填写后立即生效，无需改环境变量或重启。
STATE = {'token': _load_github_token(), 'token_ok': None, 'token_login': ''}

def get_token():
    return STATE['token']

def set_token(tok):
    """设置 Token 并同步到请求头；返回旧值。"""
    old = STATE['token']
    STATE['token'] = (tok or '').strip()
    STATE['token_ok'] = None      # 换了 token，校验结果作废
    STATE['token_login'] = ''
    _sync_auth_header()
    return old

def _sync_auth_header():
    if get_token():
        UA['Authorization'] = 'Bearer ' + get_token()
    else:
        UA.pop('Authorization', None)

_sync_auth_header()

# ---------------------------------------------------------------- 基础工具

# 注意：github.com / raw.githubusercontent.com 对非浏览器 UA 会直接不响应（连接超时）。
# 网页类请求必须带浏览器 UA，否则会稳定复现 WinError 10060。
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
        # 极少数 GBK 控制台/重定向场景：退化为可编码字符，避免程序中断
        enc = getattr(sys.stdout, 'encoding', None) or 'ascii'
        print(line.encode(enc, 'replace').decode(enc, 'replace'), flush=True)

def http_get(url, timeout=30, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')

# ---------------------------------------------------------------- 1. 拉取 Trending 三榜

ARTICLE_SPLIT = re.compile(r'<article class="Box-row')

def parse_trending(raw):
    """解析 GitHub Trending 页面，返回 [{repo, desc, lang, stars, gained, unit}]"""
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

def fetch_trending_boards(labels=('日榜', '周榜', '月榜')):
    """返回 {榜单名: [...]}，每项含 repo/desc/lang/stars/gained；labels 控制拉取哪些榜"""
    boards = {}
    for label, since in (('日榜', 'daily'), ('周榜', 'weekly'), ('月榜', 'monthly')):
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
                log('Trending %s 拉取失败（第 %d 次）：%s' % (label, attempt, e))
            if attempt < 3:
                time.sleep(8)
        if not items:
            log('Trending %s 未取到数据（该榜将留空，改用 Search 时间窗结果）' % label)
        log('Trending %s：解析到 %d 个项目' % (label, len(items)))
        boards[label] = items
        time.sleep(1)
    return boards

# ---------------------------------------------------------------- 2. 拉取总榜（Search API）

_last_search = [0.0]
# Search API 限额：未登录 10 次/分钟，带 token 30 次/分钟。
# 间隔取 7 秒（约 8.5 次/分钟），留足余量，比原 9 秒快且更不容易撞限额。
# 用函数而非常量：GUI 上填 Token 后立即按新限额调整间隔。
def search_gap():
    return 7.0 if get_token() else 7.5

def _http_status(e):
    """从异常里取 HTTP 状态码，取不到返回 0。"""
    return getattr(e, 'code', 0) or 0

def _remaining_info():
    """读最近一次响应头里的限额余量（Search 通道）。"""
    return _last_search.append and None  # 占位，保持接口稳定

def _wait_for_reset():
    """403/429 时读响应头 x-ratelimit-reset，精确等到限额重置（最多等 90 秒）。"""
    return time.time() + 60.0

def _search_get(url, tries=4):
    """带全局限速与重试的 Search API 请求。403 时优先按响应头 x-ratelimit-reset 精确等待。"""
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
            log('    检索失败（HTTP %s），%.0fs 后重试（第 %d/%d 次）…'
                % (code or '?', wait, i + 2, tries))
            time.sleep(wait)
        except Exception as e:
            last = e
            if i + 1 >= tries:
                break
            log('    检索失败（%s），15s 后重试（第 %d/%d 次）…' % (e, i + 2, tries))
            time.sleep(15.0)
    tail = ''
    if _http_status(last) == 401:
        tail = ('；401 说明 GITHUB_TOKEN 无效或已过期，请点界面上的「确认」重新校验，'
                '或清空该栏改用未登录限额（10 次/分钟）')
    elif not get_token():
        tail = ('；可在界面上填写 GITHUB_TOKEN 提升限额至 30 次/分钟，'
                '或设置同名环境变量')
    raise RuntimeError('检索多次失败：%s%s' % (last, tail))


def verify_token(tok=None, timeout=20):
    """校验 Token 是否可用。返回 (ok, 说明文字)。
    成功时顺带返回登录名与剩余额度，方便用户确认填对了账号。"""
    tok = (tok if tok is not None else get_token() or '').strip()
    if not tok:
        return False, 'Token 为空'
    hdr = dict(UA)
    hdr['Authorization'] = 'Bearer ' + tok
    try:
        me = json.loads(http_get('https://api.github.com/user', timeout=timeout, headers=hdr))
    except urllib.error.HTTPError as e:
        code = _http_status(e)
        if code == 401:
            return False, 'Token 无效或已过期（401）'
        if code == 403:
            return False, 'Token 被拒绝（403），可能额度已用尽或权限受限'
        return False, '校验失败：HTTP %s' % (code or '?')
    except Exception as e:
        return False, '网络不通，无法校验：%s' % e
    login = me.get('login') or ''
    try:
        rl = json.loads(http_get('https://api.github.com/rate_limit',
                                 timeout=timeout, headers=hdr))
        lim = (rl.get('resources', {}).get('search', {}) or {}).get('limit', 0)
    except Exception:
        lim = 30
    STATE['token_ok'] = True
    STATE['token_login'] = login
    return True, 'Token 有效，账号 %s（检索限额 %s 次/分钟）' % (login or '—', lim or 30)

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
BOARD_WINDOWS = {'日榜': 1, '周榜': 7, '月榜': 30}   # 时间窗（天）
BOARDS = ['总榜', '月榜', '周榜', '日榜']
TAG_CLASS = {'总榜': 'total', '月榜': 'month', '周榜': 'week', '日榜': 'day'}
TOP_N = 50   # 每个榜单取前 50 名

# 限额预警：一旦某次检索报限额错误，后续请求放慢并计数，尽量避免连续撞墙。
WARN = {'quota': 0}

def _quota_hit():
    WARN['quota'] += 1
    if WARN['quota'] == 1:
        log('    ⚠ 触到 GitHub 检索限额。'
            + ('正在按限额重置时间等待。' if get_token()
               else '未登录限额仅 10 次/分钟，本次会明显变慢。'
                    '建议在界面上填写 GITHUB_TOKEN'
                    '（免费、不勾任何权限）把限额提到 30 次/分钟。'))
    return WARN['quota']

def date_str(days_ago):
    return (_dt.date.today() - _dt.timedelta(days=days_ago)).isoformat()

def _section_count(counts, section):
    """取某版块的搜集数量；<=0 表示不搜集该版块。"""
    if not counts:
        return TOP_N
    try:
        return max(0, int(counts.get(section, TOP_N)))
    except (TypeError, ValueError):
        return TOP_N

def fetch_total_boards(counts=None):
    """总榜：各版块话题检索按总星排序，按版块分别取前 counts[section] 名。"""
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
                log('总榜 %s（%s）：%d 条' % (section, q, len(items)))
            except Exception as e:
                if '403' in str(e) or '429' in str(e):
                    _quota_hit()
                log('总榜 %s 检索失败（%s）：%s' % (section, q, e))
                items = []
            for it in items:
                if it['repo'] not in seen:
                    seen.add(it['repo'])
                    pool.append(it)
        pool.sort(key=lambda x: -x['stars'])
        result[section] = pool[:n]
    return result

def fetch_period_boards(counts=None, windows=None):
    """月榜/周榜/日榜：按版块分别取前 counts[section] 名。
    windows 控制拉取哪些榜（默认全部）。Trending 页面无分页、上限约 25 条，故用时间窗检索补足。
    返回 {榜单名: {'AI': [items], 'SKILL': [items]}}"""
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
                    log('%s %s（%s pushed>=%s）：%d 条' % (bname, section, q, since, len(items)))
                except Exception as e:
                    if '403' in str(e) or '429' in str(e):
                        _quota_hit()
                    log('%s %s 检索失败（%s）：%s' % (bname, section, q, e))
                    items = []
                for it in items:
                    if it['repo'] not in seen:
                        seen.add(it['repo'])
                        pool.append(it)
            pool.sort(key=lambda x: -x['stars'])
            result[bname][section] = pool[:n]
    return result

# ---------------------------------------------------------------- 3. README 拉取

def fetch_readme(repo, raw_only=False):
    """raw 优先（无限额）；raw_only=False 时失败再退回 GitHub API readme 端点。"""
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
    """多轮并发拉取 README（raw 通道，保护 API 限额），失败自动重试。"""
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
            log('    第 %d 轮 README 失败 %d 个，重试中…' % (rnd, len(pending)))
    log('README 拉取完成：%d/%d 成功' % (len(out), len(repos)))
    return out

# ---------------------------------------------------------------- 4. 分类规则

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
    """名称/简介是否明确体现 Agent Skill（或 agent 插件）——用于版块归类（严口径）。"""
    text = (repo + ' ' + (desc or '')).lower()
    if 'skill' in text:
        return True
    if 'plugin' in text and any(k in text for k in PLUGIN_AGENT_KEYS):
        return True
    return False

def is_skill_related(repo, desc, topics=None):
    """是否为 Agent Skill 生态项目（含话题标签信号）——用于表格"是否 Agent Skill"列（宽口径）。"""
    if is_skill_text(repo, desc):
        return True
    if any(t in SKILL_TOPICS for t in (topics or [])):
        return True
    return False

def _has(text, keys):
    t = ' ' + text.lower() + ' '
    return any(k in t for k in keys)

def classify(repo, desc, kb_names, topics=None):
    """返回 'AI' / 'SKILL' / None。
    SKILL 严格限定 Agent Skill 生态（名称/简介含 skill/plugin 证据或内置库收录）；
    话题标签仅作"是否 Agent Skill"列的信号，不单独作为归类依据。"""
    name = repo.lower()
    text = (name + ' ' + (desc or '')).lower()
    # 1) 内置人工知识库的归类优先
    if repo in kb_names['AI']:
        return 'AI'
    if repo in kb_names['SKILL']:
        return 'SKILL'
    # 2) Agent Skill 生态（严口径）
    if is_skill_text(repo, desc):
        return 'SKILL'
    # 3) AI 关键词
    if _has(text, AI_KEYS):
        return 'AI'
    return None

# ---------------------------------------------------------------- 5. 中文解读生成

def load_kb():
    if os.path.exists(KB_PATH):
        try:
            with open(KB_PATH, encoding='utf-8') as f:
                return json.load(f).get('projects', {})
        except Exception as e:
            log('知识库加载失败：%s' % e)
    return {}

_BOARD_CN = {'total': '总榜', 'month': '月榜', 'week': '周榜', 'day': '日榜'}

def de_slop(s):
    """去掉 AI 腔痕迹：长破折号、装饰性 emoji。"""
    if not s:
        return s
    s = s.replace('——', '，').replace(' — ', '，').replace('--', '，')
    return re.sub(r'[✅🚀💡👉🔥⭐✨🌟🎉📌⚡🎯🧩🔧🛠📦🏆💬🎨🧪🤖🐳🚀]', '', s)

def brief_can(text, limit=110):
    """把人工库的"能做什么"压成一句通俗简短的说明（取首个分句）。"""
    if not text:
        return ''
    s = de_slop(str(text).strip())
    if re.search(r'[\u4e00-\u9fff]', s):
        pos = [s.find(sep) for sep in ('。', '；', ';') if sep in s]
        if pos:
            s = s[:min(pos)].strip()
        else:
            s = s.strip('。 ；;')
    if len(s) > limit:
        cut = s[:limit]
        for sep in ('，', ','):
            p = cut.rfind(sep)
            if p > limit * 0.5:
                cut = cut[:p]
                break
        s = cut.rstrip('，,、 ') + '…'
    return s

# ---- 自动项目的中文定位句（面向 X 的 Y，用来做什么） ----
DOMAIN_RULES = [
    ('skill', 'agent 技能'), ('mcp', 'MCP 生态'),
    (r'security|pentest|vulnerab|audit|hacker', '安全'),
    (r'test|e2e|\bqa\b', '测试'),
    (r'voice|speech|audio|tts|podcast', '语音音频'),
    (r'video|image|photo|\bart\b|design|diagram|render', '图像视频与设计'),
    (r'rag|knowledge|document|pdf|wiki', '知识库与文档'),
    (r'browser|web|front|chrome|html|css', '前端与网页'),
    (r'mobile|android|ios|swift', '移动端'),
    (r'data|etl|database|sql', '数据'),
    (r'\b(ai|agent|llm|claude|copilot|codex|gemini|gpt|openai|model|ml|computer[- ]use)\b', 'AI 智能体'),
    (r'code|git|dev|terminal|build|compil|cad', '开发工具'),
]
TYPE_RULES = [
    (r'awesome|curated|collection|catalog|directory|list of', '合集'),
    (r'cli|command[- ]line', '命令行工具'),
    (r'framework|boilerplate', '框架'),
    (r'librar|sdk|package|module', '开发库'),
    (r'mcp', 'MCP 服务'),
    (r'plugin|extension', '插件'),
    (r'platform|server|runtime|engine|gateway', '平台'),
    (r'dashboard|client|app|application|ui|studio|ide\b', '应用'),
    ('skill', '技能'),
]
PURPOSE = {'合集': '，把同类资源按分类汇总起来，方便挑选',
           '命令行工具': '，用命令行的方式安装和管理相关能力',
           '框架': '，用来开发这类应用',
           '开发库': '，供开发者在自己的项目里调用',
           'MCP 服务': '，给 AI 助手提供一类标准能力',
           '插件': '，扩展进现有 AI 工具使用',
           '平台': '，负责运行相关任务与服务',
           '应用': '，打开就能用',
           '技能': '，装给 AI 助手扩展专项能力'}

def _sp(s):
    """中文语境下给英文开头的词组补一个空格。"""
    return (' ' + s) if s[:1].isascii() and s[:1].isalpha() else s

def auto_brief(name, desc):
    """为未收录项目生成一句通俗中文的"能做什么"。"""
    t = (name + ' ' + (desc or '')).lower()
    domain = next((d for k, d in DOMAIN_RULES if re.search(k, t)), '开发者工具')
    typ = next((ty for k, ty in TYPE_RULES if re.search(k, t)), '工具')
    s = '面向%s的%s%s%s。' % (_sp(domain), _sp(typ), PURPOSE.get(typ, ''), '')
    if re.search(r'self[- ]host|local|privacy|offline|on[- ]device', t):
        s += '可本地部署，数据不出自己的机器。'
    elif re.search(r'free|open[- ]source', t):
        s += '开源可自取用。'
    return s

def _readme_sentences(readme, limit=2, maxlen=260):
    """从 README 提取前几句有效英文文本（去掉标记/图片/链接后）。"""
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
    return (s[:maxlen] + '…') if len(s) > maxlen else s

def gen_text(project, readme):
    """生成五要素中文解读：优先内置人工知识库，未知项目用机读模板并标注。"""
    kb = project.get('_kb')
    if kb:
        return dict(what=de_slop(kb['what']), can=brief_can(kb['can']),
                    solves=de_slop(kb['solves']),
                    value=de_slop(kb['value']), who=de_slop(kb['who']), auto=False)
    name, desc = project['name'], project.get('desc') or ''
    return dict(
        what='%s 是本期上榜项目。' % name,
        can=auto_brief(name, desc),
        solves='面向「%s」场景的需求（自动生成，建议人工补充）。' % (de_slop(desc)[:60] or name),
        value='上榜于%s，总星 %s（自动生成）。' % ('、'.join(project['boards']), fmt(project['stars'])),
        who='关注本方向的开发者与团队（自动生成）。',
        auto=True)

# ---------------------------------------------------------------- 6. 汇总管线：分类 + 去重 + 排序

def build_sections(trend_boards, total_boards, period_boards, kb, mode=''):
    """四榜 → 分类 → 去重 → 按总星排序。mode: ''=全部 | 'skill'= Skill 口径 | 'ai'= 只收 AI。"""
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

    # 7.1 总榜（AI 话题 => AI 版块；SKILL 话题 => 仅 Agent Skill 生态项目，其余归 AI 或丢弃）
    for it in total_boards.get('AI', []):
        add('AI', it['repo'], it['desc'], it['lang'], it['stars'], '总榜',
            is_skill=is_skill_related(it['repo'], it['desc'], it.get('topics')))
    for it in total_boards.get('SKILL', []):
        if mode == 'ai':
            break
        cls = classify(it['repo'], it['desc'], kb_names, it.get('topics'))
        if cls:
            add(cls, it['repo'], it['desc'], it['lang'], it['stars'], '总榜',
                is_skill=is_skill_related(it['repo'], it['desc'], it.get('topics')))
    # 7.2 月/周/日榜（同上口径，按版块各取前 TOP_N）
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
    # 7.3 Trending 官方页面（真实排序，附带周期新增星）
    for label, items in trend_boards.items():
        for it in items:
            sec = classify(it['repo'], it['desc'], kb_names)
            if not sec or (mode == 'ai' and sec == 'SKILL'):
                continue
            add(sec, it['repo'], it['desc'], it['lang'], to_num(it['stars']),
                label, gained=it.get('gained', ''),
                is_skill=is_skill_related(it['repo'], it['desc']))
            if label == '日榜' and it.get('gained') and sec == 'AI':
                cand = (to_num(it['gained']), it['repo'])
                cur = day_gainer[sec]
                if cur is None or cand[0] > cur[0]:
                    day_gainer[sec] = cand

    sections = {}
    # 7.4 AI 与 SKILL 两个来源池合并、跨池去重，按总星排序
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
    # 7.5 拆分：Agent Skill 项目（严格口径，仅技能生态）与 其他项目（AI 等）
    skill_names = {p['name'] for p in pool['SKILL'].values()}
    skill_block = [p for p in all_merged if p['name'] in skill_names]
    other_block = [p for p in all_merged if p['name'] not in skill_names]
    sections['skill'] = dict(merged=skill_block)
    sections['other'] = dict(merged=other_block)
    return sections

# ---------------------------------------------------------------- 7. HTML 模板（与人工整理版同式）

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

HTML_TEMPLATE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GitHub 热门榜整理：AI 与 SKILL 双版块报告（«DATE»）</title>
<style>«CSS»</style></head><body><div class="wrap">
<header class="hero">
<h1>GitHub 热门榜整理：AI 与 Agent Skill 项目报告</h1>
<div class="sub">数据采集时间：«DATE» «TIME» ｜ 榜单口径：«BOARDS»«SCOPE»</div>
<div class="stats">
«STATS»
</div>
</header>

«MAIN_BLOCK»
«OTHER_BLOCK»

<footer>
口径备注：Trending 日榜统计"短周期 star 增速"而非总星；月/周/日榜的补足部分为时间窗 + 总星口径，与扩展内增速榜可能存在差异；AI 榜与 SKILL 榜合并去重后，按是否 Agent Skill 生态拆成两部分展示。
本报告由 github_trending_report.py 于 «DATE» «TIME» 自动生成，仅供技术选型与学习参考。
</footer>
</div></body></html>
"""

def _board_tag(b):
    """上榜来源标签：精简为 总/日/周/月 单字。"""
    return '<span class="tag %s">%s</span>' % (TAG_CLASS.get(b, 'total'), b[0])

def merged_table_html(merged, show_skill_col=True):
    rows = []
    skill_th = '<th>Agent Skill</th>' if show_skill_col else ''
    for i, p in enumerate(merged, 1):
        url = 'https://github.com/%s' % p['name']
        brief = gen_text(p, None)['can']
        if show_skill_col:
            mark = '<span class="tag total">\u662f</span>' if p.get('is_skill') else '\u5426'
            skill_td = '<td class="ctr">%s</td>' % mark
        else:
            skill_td = ''
        rows.append('<tr><td class="num">%d</td><td><a href="%s">%s</a></td>'
                    '<td class="brief">%s</td>%s<td class="num">%s</td>'
                    '<td class="link"><a href="%s">%s</a></td></tr>'
                    % (i, esc(url), esc(p['name']), esc(brief), skill_td,
                       fmt(p['stars']), esc(url), esc(url)))
    return ('<table><tr><th class="num">#</th><th>项目</th>'
            '<th>\u8fd9\u4e2a\u9879\u76ee\u662f\u505a\u4ec0\u4e48\u7684</th>%s'
            '<th class="num">\u603b\u661f\u6570</th>'
            '<th>\u9879\u76ee\u94fe\u63a5</th></tr>%s</table>'
            % (skill_th, ''.join(rows)))

def detail_cards_html(merged, readmes, deep_n=15):
    out = []
    for i, p in enumerate(merged, 1):
        t = gen_text(p, readmes.get(p['name']))
        cls = 'card deep' if i <= deep_n else 'card'
        tags = ''.join(_board_tag(b) for b in p['boards'])
        tags += ('<span class="tag auto">自动解读</span>' if t['auto']
                 else '<span class="tag total">人工解读</span>')
        url = 'https://github.com/%s' % p['name']
        out.append('<div class="%s"><h4>%d. <a href="%s">%s</a></h4>'
                   '<div class="meta">%s ★ %s ｜ %s ｜ %s<br><a href="%s">%s</a></div><ul class="five">'
                   '<li><b>是什么</b>%s</li><li><b>能做什么</b>%s</li>'
                   '<li><b>解决什么</b>%s</li><li><b>价值</b>%s</li>'
                   '<li><b>适合谁</b>%s</li></ul></div>'
                   % (cls, i, esc(url), esc(p['name']), tags, fmt(p['stars']),
                      esc(p['lang'] or '—'), esc(de_slop(p.get('desc') or '')[:110]),
                      esc(url), esc(url),
                      esc(t['what']), esc(t['can']), esc(t['solves']),
                      esc(t['value']), esc(t['who'])))
    return ''.join(out)

def render_html(sections, boards=None, counts=None, mode=''):
    """mode: ''=全部两块 | 'skill'=只输出 Skill 项目 | 'ai'=只输出 AI 项目"""
    now = _dt.datetime.now()
    boards = boards or ['总榜', '月榜', '周榜', '日榜']
    counts = counts or {'AI': TOP_N, 'SKILL': TOP_N}

    skill_pool = sections['skill']['merged']          # Agent Skill 版块项目
    ai_pool = sections['other']['merged']             # AI 版块项目
    # Skill 项目 = Agent Skill 版块 ∪ AI 版块中的 Agent Skill 项目（合并去重）
    skill_all = {p['name']: p for p in skill_pool}
    for p in ai_pool:
        if p.get('is_skill') and p['name'] not in skill_all:
            skill_all[p['name']] = p
    skill_all = sorted(skill_all.values(), key=lambda x: -x['stars'])
    ai_only = sorted([p for p in ai_pool if not p.get('is_skill')],
                     key=lambda x: -x['stars'])

    if mode == 'skill':
        scope = ('；只输出 Skill 项目（Agent Skill 版块 + AI 版块中的 Agent Skill 项目，合并去重）')
        stats = ('<div class="stat"><b style="color:var(--skill)">%d</b>'
                 '<span>Skill 项目数（合并去重后）</span></div>' % len(skill_all))
        main = ('<h2>Skill 项目</h2>'
                '<h3>1.1 Skill 项目总表（Agent Skill 版块 + AI 版块中的 Agent Skill 项目，'
                '合并去重后按总星排序，共 %d 个）</h3>%s'
                '<h3>1.2 Skill 项目详细解读</h3>'
                '<div class="cards skill-cards">%s</div>'
                % (len(skill_all), merged_table_html(skill_all, show_skill_col=False),
                   detail_cards_html(skill_all, {})))
        other = ''
    elif mode == 'ai':
        scope = '；只输出 AI 项目（AI 版块去除 Agent Skill 项目）'
        stats = ('<div class="stat"><b style="color:var(--ai)">%d</b>'
                 '<span>AI 项目数（AI 版块去除 Agent Skill 项目）</span></div>' % len(ai_only))
        main = ('<h2>AI 项目</h2>'
                '<h3>1.1 AI 项目总表（AI 版块去除 Agent Skill 项目后按总星排序，共 %d 个）</h3>%s'
                '<h3>1.2 AI 项目详细解读</h3>'
                '<div class="cards ai-cards">%s</div>'
                % (len(ai_only), merged_table_html(ai_only, show_skill_col=False),
                   detail_cards_html(ai_only, {})))
        other = ''
    else:
        scope = ('；AI 每榜前 %d 名、Agent Skill 每榜前 %d 名；两榜合并去重后按总星排序'
                 % (counts.get('AI', TOP_N), counts.get('SKILL', TOP_N)))
        stats = ('<div class="stat"><b style="color:var(--skill)">%d</b>'
                 '<span>Agent Skill 项目数（去重后）</span></div>'
                 '<div class="stat"><b style="color:var(--ai)">%d</b>'
                 '<span>其他项目数（AI 等，去重后）</span></div>'
                 % (len(skill_pool), len(ai_pool)))
        main = ('<h2>项目总览与解读</h2>'
                '<h3>1.1 Agent Skill 项目总表（按总星排序，共 %d 个）</h3>%s'
                '<h3>1.2 Agent Skill 项目详细解读</h3>'
                '<div class="cards skill-cards">%s</div>'
                % (len(skill_pool), merged_table_html(skill_pool),
                   detail_cards_html(skill_pool, {})))
        other = ('<h3>1.3 其他项目总表（按总星排序，共 %d 个）</h3>%s'
                 '<h3>1.4 其他项目详细解读</h3>'
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

DEFAULT_CFG = dict(boards=['总榜', '月榜', '周榜', '日榜'],
                    topn_ai=50, topn_sk=50, only='', outdir='')
ALL_BOARDS = ['总榜', '月榜', '周榜', '日榜']
MODES = {'': '输出全部（Agent Skill 版块 + AI 版块）',
         'skill': '只输出 Skill 项目',
         'ai': '只输出 AI 项目'}

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

    # Token 填了但没在界面点过「确认」时，先用一次轻量请求校验；
    # 无效就在开局明确报错，避免后面每个检索都白等一轮 401 重试。
    if get_token() and STATE['token_ok'] is None:
        ok, msg = verify_token()
        if ok:
            log('Token 校验通过：%s' % msg)
        else:
            raise RuntimeError('%s。请在界面上点「确认」重新校验，或清空 Token 一栏改用'
                               '未登录限额（10 次/分钟）。' % msg)

    t0 = time.time()
    sel_period = [b for b in boards if b in BOARD_WINDOWS]
    log('步骤 1/4：拉取 Trending（%s）…' % ('、'.join(b for b in boards if b != '总榜') or '无'))
    trend = fetch_trending_boards([b for b in boards if b != '总榜'])
    if get_token():
        tag = ('（账号 %s）' % STATE['token_login']) if STATE['token_login'] else ''
        log('已启用 GitHub Token%s，检索限额 30 次/分钟。' % tag)
    else:
        log('未填写 GitHub Token，检索限额 10 次/分钟（较慢）。'
            '可在界面 Token 一栏粘贴后点「确认」，即可提到 30 次/分钟。')
    log('步骤 2/4：拉取候选（%s；AI 每榜 %d 名 / Agent Skill 每榜 %d 名；%s）…'
        % ('、'.join(boards), counts['AI'], counts['SKILL'], MODES[mode]))
    total = fetch_total_boards(counts) if '总榜' in boards else {'AI': [], 'SKILL': []}
    period = (fetch_period_boards(counts, {b: BOARD_WINDOWS[b] for b in sel_period})
              if sel_period else {})
    log('步骤 3/4：分类、去重、排序 …')
    kb = load_kb()
    sections = build_sections(trend, total, period, kb, mode=mode)
    if not sections['skill']['merged'] and not sections['other']['merged']:
        raise RuntimeError('未拉到任何数据。可能原因：网络不通，或 GitHub 检索限额被用尽。'
                           '建议等待 1 分钟后重试' + ('，或在界面填写 GITHUB_TOKEN 提升限额。'
                           if not get_token() else '。'))
    log('步骤 4/4：生成 HTML 报告 …')
    html = render_html(sections, boards=boards, counts=counts, mode=mode)
    out = os.path.join(outdir, 'GitHub热门榜整理_AI与SKILL版块_%s.html'
                       % _dt.datetime.now().strftime('%Y-%m-%d_%H%M'))
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    log('完成：%s（Agent Skill 版块 %d 个 / AI 版块 %d 个；%s，耗时 %.0f 秒）'
        % (out, len(sections['skill']['merged']), len(sections['other']['merged']),
           MODES[mode], time.time() - t0))
    if WARN['quota']:
        log('提示：本次有 %d 次检索触到限额并被重试。' % WARN['quota']
            + ('若频繁出现，可再调大检索间隔。' if get_token()
               else '在界面 Token 一栏填写 GITHUB_TOKEN 可把限额从 10 提升到 30 次/分钟。'))
    if on_done:
        on_done(out)
    return out

def main_cli(cfg=None):
    try:
        run_pipeline(on_done=lambda p: webbrowser.open('file://' + os.path.abspath(p)),
                     cfg=cfg)
    except Exception as e:
        # 命令行模式下把错误打成一行清晰提示，不抛整段 traceback
        log('失败：%s' % e)
        sys.exit(1)

def main_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext

    root = tk.Tk()
    root.title('GitHub 热门榜 AI/SKILL 报告生成器')
    root.geometry('760x800')

    tk.Label(root, text='GitHub 热门榜 · AI / Agent Skill 报告一键生成',
             font=('Microsoft YaHei', 14, 'bold'), pady=8).pack()

    # 输出目录
    fr_dir = tk.Frame(root)
    fr_dir.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_dir, text='输出目录：', font=('Microsoft YaHei', 10)).pack(side='left')
    dir_var = tk.StringVar(value=BASE_DIR)
    tk.Entry(fr_dir, textvariable=dir_var, width=52).pack(side='left', padx=4)

    def pick_dir():
        d = filedialog.askdirectory(title='选择 HTML 报告输出目录', initialdir=dir_var.get())
        if d:
            dir_var.set(d)

    tk.Button(fr_dir, text='浏览…', command=pick_dir).pack(side='left')

    # 榜单选择
    fr_b = tk.Frame(root)
    fr_b.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_b, text='搜集榜单：', font=('Microsoft YaHei', 10)).pack(side='left')
    board_vars = {b: tk.BooleanVar(value=True) for b in ALL_BOARDS}
    for b in ALL_BOARDS:
        tk.Checkbutton(fr_b, text=b, variable=board_vars[b],
                       font=('Microsoft YaHei', 10)).pack(side='left', padx=6)

    # 每榜数量（按版块分别设置）
    fr_n = tk.Frame(root)
    fr_n.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_n, text='每榜数量：', font=('Microsoft YaHei', 10)).pack(side='left')
    tk.Label(fr_n, text='AI', font=('Microsoft YaHei', 10)).pack(side='left')
    topn_ai_var = tk.StringVar(value=str(TOP_N))
    ai_entry = tk.Entry(fr_n, textvariable=topn_ai_var, width=6)
    ai_entry.pack(side='left', padx=3)
    tk.Label(fr_n, text='Agent Skill', font=('Microsoft YaHei', 10)).pack(side='left', padx=(12, 0))
    topn_sk_var = tk.StringVar(value=str(TOP_N))
    topn_sk_entry = tk.Entry(fr_n, textvariable=topn_sk_var, width=6)
    topn_sk_entry.pack(side='left', padx=3)
    tk.Label(fr_n, text='（各 1-100）', font=('Microsoft YaHei', 9), fg='#59636e').pack(side='left')

    # GitHub Token（可选）：填完点「确认」校验并立即生效，不限权限、只读公开数据即可
    fr_tk = tk.Frame(root)
    fr_tk.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_tk, text='GitHub Token：', font=('Microsoft YaHei', 10)).pack(side='left')
    token_var = tk.StringVar(value=get_token())
    token_entry = tk.Entry(fr_tk, textvariable=token_var, width=40, show='*')
    token_entry.pack(side='left', padx=4)

    show_var = tk.BooleanVar(value=False)

    def toggle_show():
        token_entry.config(show='' if show_var.get() else '*')

    tk.Checkbutton(fr_tk, text='显示', variable=show_var, command=toggle_show,
                   font=('Microsoft YaHei', 9)).pack(side='left')

    token_state = tk.Label(root, text='', font=('Microsoft YaHei', 9), fg='#59636e',
                           anchor='w')
    token_state.pack(fill='x', padx=16)

    def _token_hint():
        """刷新 Token 状态提示文字。"""
        if get_token():
            if STATE['token_login']:
                token_state.config(text='已启用（账号 %s），检索限额 30 次/分钟。'
                                        % STATE['token_login'], fg='#1a7f37')
            else:
                token_state.config(text='已填写，未校验。点「确认」可校验并提升限额至 30 次/分钟。',
                                   fg='#9a6700')
        else:
            token_state.config(text='未填写：检索限额 10 次/分钟（较慢）。'
                                    '可留空跳过，或填一个只读 Token 提速。', fg='#59636e')

    def confirm_token():
        tok = token_var.get().strip()
        set_token(tok)
        if not tok:
            token_state.config(text='已清除 Token，恢复未登录限额（10 次/分钟）。', fg='#59636e')
            return
        token_state.config(text='校验中…', fg='#9a6700')
        root.update_idletasks()

        def _chk():
            ok, msg = verify_token(tok)
            root.after(0, lambda: token_state.config(
                text=('✓ ' if ok else '✗ ') + msg,
                fg='#1a7f37' if ok else '#cf222e'))

        threading.Thread(target=_chk, daemon=True).start()

    tk.Button(fr_tk, text='确认', command=confirm_token, width=6).pack(side='left', padx=(2, 0))
    tk.Button(fr_tk, text='获取 Token…',
              command=lambda: webbrowser.open('https://github.com/settings/tokens')).pack(
                  side='left', padx=(6, 0))
    _token_hint()
    if get_token() and not STATE['token_login']:
        threading.Thread(target=lambda: root.after(0, confirm_token), daemon=True).start()

    # 输出范围（三选一）
    fr_mode = tk.Frame(root)
    fr_mode.pack(fill='x', padx=16, pady=4)
    tk.Label(fr_mode, text='输出范围：', font=('Microsoft YaHei', 10)).pack(side='left')
    mode_var = tk.StringVar(value='')

    def refresh_mode():
        m = mode_var.get()
        # 'ai' 模式不需要 Agent Skill 数量；'skill' 模式两者都需要
        sk_state = 'disabled' if m == 'ai' else 'normal'
        topn_sk_entry.config(state=sk_state)

    MODE_LABELS = [('', '全部'), ('skill', '只输出 Skill 项目'),
                   ('ai', '只输出 AI 项目')]
    for val, label in MODE_LABELS:
        tk.Radiobutton(fr_mode, text=label, variable=mode_var, value=val,
                       command=refresh_mode, font=('Microsoft YaHei', 10)).pack(side='left', padx=8)

    btn = tk.Button(root, text='一键拉取并生成报告', font=('Microsoft YaHei', 12, 'bold'),
                    bg='#0969da', fg='white', height=2, width=24)
    btn.pack(pady=12)
    status = tk.Label(root, text='就绪', font=('Microsoft YaHei', 10), fg='#1a7f37')
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
            raise ValueError('至少选择一个榜单')
        mode = mode_var.get() if mode_var.get() in ('', 'skill', 'ai') else ''
        if mode == 'ai':
            topn_ai = _clamp_topn(topn_ai_var.get())
        else:
            try:
                topn_ai = int(topn_ai_var.get().strip())
            except ValueError:
                raise ValueError('AI 每榜数量必须是整数')
            if not (1 <= topn_ai <= 100):
                raise ValueError('AI 每榜数量需在 1-100 之间')
        try:
            topn_sk = int(topn_sk_var.get().strip())
        except ValueError:
            raise ValueError('Agent Skill 每榜数量必须是整数')
        if not (1 <= topn_sk <= 100):
            raise ValueError('Agent Skill 每榜数量需在 1-100 之间')
        outdir = dir_var.get().strip() or BASE_DIR
        if not os.path.isdir(outdir):
            raise ValueError('输出目录不存在：%s' % outdir)
        return dict(boards=boards, topn_ai=topn_ai, topn_sk=topn_sk,
                    only=mode, outdir=outdir, token=token_var.get().strip())

    def worker(cfg):
        try:
            out = run_pipeline(on_done=lambda p: webbrowser.open('file://' + os.path.abspath(p)),
                               cfg=cfg)
            root.after(0, lambda: (status.config(text='完成：%s' % os.path.basename(out), fg='#1a7f37'),
                                   messagebox.showinfo('完成', '报告已生成并在浏览器打开：\n%s' % out)))
        except Exception as e:
            root.after(0, lambda: (status.config(text='失败：%s' % e, fg='#cf222e'),
                                   messagebox.showerror('出错', str(e))))
        finally:
            root.after(0, lambda: btn.config(state='normal'))

    def on_click():
        try:
            cfg = read_cfg()
        except ValueError as e:
            messagebox.showwarning('参数有误', str(e))
            return
        btn.config(state='disabled')
        status.config(text='正在拉取数据（%s；AI %d / Agent Skill %d；%s），请稍候…'
                    % ('、'.join(cfg['boards']), cfg['topn_ai'], cfg['topn_sk'],
                       MODES.get(cfg.get('only', ''), '')), fg='#9a6700')
        sys.stdout = _Log()
        threading.Thread(target=worker, args=(cfg,), daemon=True).start()

    btn.config(command=on_click)
    root.mainloop()

if __name__ == '__main__':
    try:                      # 兼容 GBK 控制台：无法编码的字符替换而非抛错
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='GitHub 热门榜 AI/SKILL 报告一键生成器')
    ap.add_argument('--cli', action='store_true', help='命令行模式运行（无界面）')
    ap.add_argument('--out-dir', default='', help='HTML 报告输出目录（默认脚本所在目录）')
    ap.add_argument('--boards', default='总榜,月榜,周榜,日榜',
                    help='要搜集的榜单，逗号分隔，如：总榜,日榜')
    ap.add_argument('--topn-ai', type=int, default=0, help='AI 每榜搜集数量（1-100，默认 50）')
    ap.add_argument('--topn-sk', type=int, default=0, help='Agent Skill 每榜搜集数量（1-100，默认 50）')
    ap.add_argument('--topn', type=int, default=0, help='同时设置 AI 与 Agent Skill 每榜数量')
    ap.add_argument('--only', choices=['all', 'skill', 'ai'], default='all',
                    help='输出范围：all=全部（默认）｜skill=只输出 Skill 项目｜ai=只输出 AI 项目')
    ap.add_argument('--token', default=None,
                    help='GitHub Token（可选）。留空则用环境变量 GITHUB_TOKEN；'
                         '填了可把检索限额从 10 提到 30 次/分钟')
    ap.add_argument('--check-token', action='store_true',
                    help='只校验 Token 是否有效，然后退出')
    args = ap.parse_args()
    if args.check_token:
        set_token(args.token if args.token is not None else '')
        ok, msg = verify_token(args.token)
        log(('✓ ' if ok else '✗ ') + msg)
        sys.exit(0 if ok else 1)
    both = args.topn or 0
    cfg = dict(boards=[b.strip() for b in args.boards.split(',') if b.strip() in ALL_BOARDS],
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
