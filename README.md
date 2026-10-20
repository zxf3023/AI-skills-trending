<h1 align="center">AI Skills Trending</h1>

<p align="center">
  <strong>一份 HTML 报告，看清 GitHub 上正在涨的 AI 与 Agent Skill 项目。</strong><br />
  拉取榜单、逐个归类、跨榜去重，写成一份带解读的 HTML 报告。
</p>

<p align="center">
  <a href="#快速开始"><strong>快速开始</strong></a>
  ·
  <a href="#报告里有什么">报告内容</a>
  ·
  <a href="#github-token可选但推荐">GitHub Token</a>
  ·
  <a href="#命令行">命令行</a>
  ·
  <a href="#数据口径">数据口径</a>
  ·
  <a href="#故障排查">故障排查</a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.8%2B-3776AB?logo=python&logoColor=white" alt="Python 3.8 或更高" /></a>
  <img src="https://img.shields.io/badge/dependencies-none-2ea44f" alt="无依赖" />
  <img src="https://img.shields.io/badge/pip%20install-not%20required-2ea44f" alt="无需 pip 安装" />
  <img src="https://img.shields.io/badge/license-not%20specified-lightgrey" alt="未指定许可证" />
</p>

<div align="center">

中文 | [English](./README_en.md)

</div>

---

## 这是什么

GitHub 的 trending 榜单里，模型发布、技能包和一堆无关项目排在一起。想从中挑出值得看的，得翻很久。

AI Skills Trending 替你做完这一遍。跑一次就会拉取官方 Trending 榜单和话题检索结果，把项目分成 **AI** 与 **Agent Skill** 两类，跨榜去重，按总星排序。最后输出一份 HTML 报告，每个项目带链接、星数，和一句说明它能干什么的人话。

程序只用 Python 标准库，不需要装任何东西，图形界面和命令行都能用。

---

## 一次运行做了什么

| 步骤 | 动作 |
|---|---|
| **1. 拉取** | 拉取 GitHub 官方 Trending 的日榜、周榜、月榜 |
| **2. 补足** | 用话题检索补齐总榜、月榜、周榜、日榜，每榜取前 N 名 |
| **3. 归类** | 分入 AI 或 Agent Skill 版块，跨榜去重，按总星排序 |
| **4. 渲染** | 写出 HTML 报告：汇总表加每个项目的详细卡片 |

总榜来自 GitHub Search 按总星排序。月榜、周榜、日榜是 Trending 页面加时间窗检索的组合，因为 Trending 页面没有分页，最多只到 25 条左右。

---

## 快速开始

### 环境要求

- Python 3.8 或更高版本（[下载](https://www.python.org/downloads/)）
- 安装时勾选 **Add python.exe to PATH**
- 不需要任何第三方库

### 方式一：一键启动（Windows）

双击 `run_report.bat`。启动器按顺序探测解释器：`py -3` → `python` → 微软商店版。都没找到就打印下载地址并暂停，窗口不会一闪而过。

### 方式二：图形界面

```bash
python github_trending_report.py
```

| 选项 | 作用 |
|---|---|
| Output folder | HTML 报告保存位置，可点 **Browse...** 选择 |
| Boards | All-time / Monthly / Weekly / Daily，可任意勾选 |
| Per-board limit | AI 与 Agent Skill 分别设置，各 1-100 |
| Output scope | Everything / Skill projects only / AI projects only |
| GitHub Token | 可选。粘贴后点 **Confirm** 校验并生效 |

> 界面与报告正文都是英文。项目从早期中文版迁移而来，程序与报告已统一为英文，文档提供中英双版。

### 方式三：命令行

```bash
python github_trending_report.py --cli \
    --out-dir "D:/reports" \
    --boards all-time,monthly,weekly,daily \
    --topn-ai 50 --topn-sk 50 \
    --only all \
    --token ghp_xxx
```

| 参数 | 说明 |
|---|---|
| `--cli` | 命令行模式运行，不弹界面 |
| `--out-dir` | HTML 输出目录，默认脚本所在目录 |
| `--boards` | 榜单，逗号分隔，大小写不敏感 |
| `--topn-ai` / `--topn-sk` | AI / Agent Skill 每榜数量，1-100 |
| `--topn` | 同时设置两者 |
| `--only` | `all`、`skill` 或 `ai` |
| `--token` | 可选 GitHub Token |
| `--check-token` | 只校验 Token 后退出 |

---

## 输出范围

| 范围 | 得到什么 |
|---|---|
| **Everything**（默认） | 1.1 Agent Skill 项目 → 1.2 Agent Skill 项目详细解读 → 1.3 其他项目 → 1.4 其他项目详细解读 |
| **Skill projects only** | 两个版块的 Agent Skill 项目合并去重后单块输出 |
| **AI projects only** | AI 版块剔除 Agent Skill 项目后的其余项目 |

报告就是汇总表，加上每个项目的解读。

---

## 报告里有什么

每个项目都有一行汇总表记录，加一张详细卡片。卡片包含五个字段：

| 字段 | 内容 |
|---|---|
| **What it is** | 一句话说明这是什么项目 |
| **What it does** | 通俗说明你会拿它干什么 |
| **What it solves** | 它解决的需求 |
| **Why it matters** | 它在同类里的位置，带星数 |
| **Who it is for** | 适合哪些人或团队 |

卡片会标 **Curated** 或 **Auto-generated**。`kb.json` 收录了 67 个项目的人工解读；不在库里的项目会走自动生成，并明确标注，方便你判断哪些需要自己再核一遍。

---

## GitHub Token（可选，但推荐）

未登录时，GitHub 给每个 IP 每分钟 **10 次**检索额度，超了返回 `403 rate limit exceeded`。程序会等待并重试，整轮照样能跑完，只是慢一些。

一个只读 Token 能把限额提到 **每分钟 30 次**，等待时间明显变短。

> [!NOTE]
> Token **不需要勾任何权限**。读取公开数据就够了，生成时不要勾选任何 scope。

**界面方式：** 把 Token 粘贴到 **GitHub Token** 一栏，点 **Confirm**，当场校验并显示账号名。输入框默认圆点遮蔽，勾 **Show** 可显示。**Get a token...** 按钮会直接打开生成页。

**环境变量方式：** 设 `GITHUB_TOKEN`（或 `GH_TOKEN`）。适合脚本或定时任务。

Token 只保存在当前这次运行的内存里，不写文件、不上传。

---

## 数据口径

- Trending **日榜**按短期 star 增速排序，不是总星。
- 月榜、周榜、日榜是「时间窗 + 总星」检索补足的，与扩展内的增速榜可能有差异。
- AI 与 SKILL 两个池子会先合并、去重，再拆成 Agent Skill 与其他两部分。
- Agent Skill 的判定刻意从严：只有名称或简介里出现 skill / plugin 证据，或被人工库收录，才归入该版块。话题标签单独不足以决定归类。
- 星数与排名是实时抓取的，每次运行都会变化。

---

## 文件说明

| 文件 | 用途 |
|---|---|
| `github_trending_report.py` | 主程序：图形界面 + 命令行，纯标准库 |
| `kb.json` | 67 个项目的人工解读。删掉也能跑，新项目改走自动生成 |
| `run_report.bat` | Windows 启动器。自动探测 Python，纯 ASCII，CRLF 换行 |
| `USAGE.txt` | 英文使用说明，含报错对照表 |
| `README.md` | 本文件（中文） |
| `README_en.md` | [English version](./README_en.md) |

---

## 故障排查

| 现象 | 原因与处理 |
|---|---|
| `'xxx' 不是内部或外部命令` | `.bat` 被编辑器或压缩工具改成了 LF 换行，或混入了非 ASCII 注释，导致 cmd 把注释当命令执行。用仓库里的启动器，它是纯 ASCII + CRLF |
| `系统找不到指定的路径` | 旧版启动器写死了别台机器的 Python 路径。现在改为自动探测 |
| 没弹窗口但程序在跑 | 你的 Python 缺 `tkinter`。程序会自动转命令行模式，属正常现象 |
| `403 rate limit exceeded` | 匿名检索额度用尽。程序会等待重试；加 Token 可提到每分钟 30 次 |
| 每次检索都报 `401` | Token 无效或已过期。点界面上的 **Confirm** 重新校验，或清空该栏回退到匿名限额 |

---

## 说明

- 完整跑一轮约 2-5 分钟，大部分时间花在等限流间隔。
- 需要联网（`github.com` 与 `api.github.com`）。
- 报告文件名带时间戳，重复运行不会覆盖旧报告。

---

## 许可

本仓库未指定许可证，仅供参考与个人使用。
