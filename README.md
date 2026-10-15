# GitHub 热门榜 AI / Agent Skill 报告生成器

一键实时拉取 GitHub 榜单，自动分类、去重、排序，生成一份 HTML 报告：哪些项目是 Agent Skill、哪些是 AI，各自总星多少、能用来做什么。

纯 Python 标准库实现，**无需 pip 安装任何依赖**。图形界面 + 命令行双模式。

## 它做什么

1. 实时拉取 GitHub 官方 Trending 日榜 / 周榜 / 月榜
2. 按版块拉取总榜 / 月榜 / 周榜 / 日榜前 N 名
   - 总榜：GitHub Search 按总星排序
   - 月/周/日榜：同话题 + 时间窗检索补足
3. 按 AI / Agent Skill 分类，跨榜去重，按总星排序
4. 生成 HTML 报告，每个项目附链接、总星数与一句通俗中文说明

## 快速开始

### 环境要求

- Python 3.8 或更高版本（[下载](https://www.python.org/downloads/)）
- 安装时勾选 **Add python.exe to PATH**
- 不需要 pip 安装任何第三方库

### 运行

**方式一：一键启动（Windows）**

双击 `一键生成报告.bat`。启动器会自动探测 Python（`py -3` → `python` → 微软商店版）。

**方式二：图形界面**

```bash
python github_trending_report.py
```

界面上可设置：

| 项目 | 说明 |
| --- | --- |
| 输出目录 | HTML 报告保存位置，可点「浏览…」选择 |
| 搜集榜单 | 总榜 / 月榜 / 周榜 / 日榜，可任意勾选 |
| 每榜数量 | AI 与 Agent Skill 分别设置，各 1-100 |
| 输出范围 | 全部 / 只输出 Skill 项目 / 只输出 AI 项目 |
| GitHub Token | 可选，填完点「确认」当场生效 |

**方式三：命令行**

```bash
python github_trending_report.py --cli \
    --out-dir "D:/报告" \
    --boards 总榜,月榜,周榜,日榜 \
    --topn-ai 50 --topn-sk 50 \
    --only all \
    --token ghp_xxx
```

| 参数 | 说明 |
| --- | --- |
| `--cli` | 命令行模式运行（无界面） |
| `--out-dir` | HTML 输出目录，默认脚本所在目录 |
| `--boards` | 要搜集的榜单，逗号分隔 |
| `--topn-ai` / `--topn-sk` | AI / Agent Skill 每榜数量（1-100） |
| `--topn` | 同时设置两者 |
| `--only` | `all` / `skill` / `ai` |
| `--token` | GitHub Token，可选 |
| `--check-token` | 只校验 Token 是否有效后退出 |

## 输出范围三选一

- **全部**（默认）：1.1 Agent Skill 项目总表 → 1.2 Agent Skill 项目详细解读 → 1.3 其他项目总表 → 1.4 其他项目详细解读
- **只输出 Skill 项目**：两个版块的 Agent Skill 项目合并去重后单块展示
- **只输出 AI 项目**：AI 版块剔除 Agent Skill 项目后的其余项目

## 关于 GitHub Token（可选，推荐配）

GitHub 对检索类接口限流严格：**未登录每 IP 每分钟 10 次**，超了会返回 `403 rate limit exceeded`（程序会自动等待重试，不会中断，但整轮会明显变慢）。

配一个只读 Token 可把限额提到 **30 次/分钟**，整轮快 1-2 分钟。两种配法：

- **界面方式（推荐）**：在「GitHub Token」一栏粘贴后点「确认」，程序当场校验并显示账号名，立即生效。点「获取 Token…」可直接打开生成页（选 Classic，**不用勾任何权限**）。
- **环境变量方式**：设 `GITHUB_TOKEN`（或 `GH_TOKEN`）。适合命令行/自动化场景。

Token 只保存在当前运行的内存里，不写文件、不上传。

## 数据口径说明

- Trending 日榜统计的是「短周期 star 增速」，不是总星
- 月/周/日榜的补足部分为「时间窗 + 总星」口径，与扩展内的增速榜可能存在差异
- AI 榜与 SKILL 榜合并去重后，按是否属于 Agent Skill 生态拆成两部分展示

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `github_trending_report.py` | 主程序（GUI + 命令行双模式，纯标准库） |
| `kb.json` | 人工解读知识库。删除后仍可运行，只是新项目都走自动生成解读 |
| `一键生成报告.bat` | Windows 一键启动器（自动探测 Python，纯 ASCII + CRLF） |
| `使用说明.txt` | 面向使用者的中文说明，含常见报错对照表 |

## 已知注意事项

- 单次运行约 2-5 分钟，主要耗时在 GitHub 接口的限流等待间隔
- 需要联网（访问 `github.com` 与 `api.github.com`）
- 报告文件名带时间戳，重复运行不会覆盖旧报告
- 数据为实时抓取，星数与榜单排名每次都会变化

## 许可

仅供技术选型与学习参考。
