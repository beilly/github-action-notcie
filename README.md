# GitHub Action Notice — 仓库动态 → Telegram 推送

订阅任意公开 GitHub 仓库的 **Release / Tag / Commit**，通过 Telegram Bot 实时通知。

## 功能

| 特性 | 说明 |
|------|------|
| 多仓库订阅 | 在 `subscriptions.yaml` 中添加任意数量的仓库 |
| 三种模式 | `release` · `tag` · `commit` |
| 消息模板自定义 | 全局默认 + 单仓库覆盖 |
| 防重复推送 | `state.json` 记录已推送 ID，每次运行后自动提交回仓库 |
| 定时检查 | GitHub Actions cron 默认每 30 分钟一次 |

## 快速开始

### 1. Fork / 使用此仓库

### 2. 创建 Telegram Bot

1. 找 [@BotFather](https://t.me/BotFather)，`/newbot` 创建 Bot，获得 **Bot Token**
2. 给 Bot 发一条消息，然后访问 `https://api.telegram.org/bot<TOKEN>/getUpdates` 获取 **Chat ID**

### 3. 配置 Secrets

在仓库 **Settings → Secrets and variables → Actions** 中添加：

| Secret | 说明 |
|--------|------|
| `TG_BOT_TOKEN` | Telegram Bot Token |
| `TG_CHAT_ID` | 接收通知的 Chat ID（个人 / 群组 / 频道均可） |

> `GITHUB_TOKEN` 由 Actions 自动提供，无需手动配置。如需提高 API 限额可用 PAT。

### 4. 编辑订阅

修改 `subscriptions.yaml`：

```yaml
subscriptions:
  - repo: nicevoice/github-action-notice
    mode: release
    include_prerelease: false

  - repo: vercel/next.js
    mode: tag

  - repo: torvalds/linux
    mode: commit
    branch: master
```

### 5. 触发运行

- 等待 cron 自动运行
- 或前往 **Actions → Check & Notify → Run workflow** 手动触发

---

## 配置说明

### subscriptions.yaml

```yaml
defaults:
  templates:
    release: |
      🚀 *{repo}* 发布新版本 [{tag}]({url})
      {body}
    tag: |
      🏷️ *{repo}* 新标签 `{tag}`
      [查看]({url})
    commit: |
      📝 *{repo}* 新提交 `{branch}`
      `{sha_short}` {message}
      [查看]({url})

subscriptions:
  - repo: owner/name      # 必填
    mode: release          # release | tag | commit
    include_prerelease: false   # 仅 release 模式有效
    branch: main           # 仅 commit 模式有效
    template: |            # 可选，覆盖全局模板
      自定义消息 {repo} {tag}
```

### 模板变量

| 变量 | release | tag | commit | 说明 |
|------|:---:|:---:|:---:|------|
| `{repo}` | ✅ | ✅ | ✅ | 仓库全名 `owner/repo` |
| `{tag}` | ✅ | ✅ | — | 标签名 |
| `{url}` | ✅ | ✅ | ✅ | 链接 |
| `{body}` | ✅ | — | — | Release 描述（截断至 500 字） |
| `{name}` | ✅ | — | — | Release 标题 |
| `{sha}` | — | ✅ | ✅ | 完整 commit SHA |
| `{sha_short}` | — | ✅ | ✅ | 7 位短 SHA |
| `{message}` | — | — | ✅ | Commit 首行消息 |
| `{branch}` | — | — | ✅ | 分支名 |
| `{author}` | — | — | ✅ | Commit 作者 |

## 防重复推送机制

- 每次运行后，将已推送事件的 ID 写入 `state.json`
- Workflow 最后一步自动将 `state.json` 提交回仓库
- 首次运行仅推送最新 5 条，避免消息轰炸

## 调整检查频率

编辑 `.github/workflows/check.yml` 中的 cron 表达式：

```yaml
schedule:
  - cron: "*/30 * * * *"   # 每 30 分钟
  - cron: "0 * * * *"      # 每小时
  - cron: "0 */6 * * *"    # 每 6 小时
```

## License

MIT
