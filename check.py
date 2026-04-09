#!/usr/bin/env python3
"""
GitHub Release / Tag / Commit → Telegram 通知
读取 subscriptions.yaml，检查每个仓库的新事件，
通过 Telegram Bot 推送通知，并把已推送 ID 持久化到 state.json。
"""

import json
import os
import sys
import textwrap
from pathlib import Path

import requests
import yaml

# ── 路径 ──
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "subscriptions.yaml"
STATE_PATH = ROOT / "state.json"

# ── 环境变量 ──
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

GITHUB_API = "https://api.github.com"

# Telegram MarkdownV2 需要转义的特殊字符。
TG_MD_V2_SPECIALS = "_[]()~`>#+-=|{}.!*"


# ───────────────────── 工具函数 ─────────────────────

def gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_telegram(text: str) -> bool:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] TG_BOT_TOKEN / TG_CHAT_ID 未设置，跳过推送")
        return False

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    text = text.replace("\x00", "")
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    resp = requests.post(url, json=payload, timeout=30)
    if resp.ok:
        print("[OK] Telegram 推送成功")
        return True

    # release body 常含特殊字符，Markdown 解析失败时降级为纯文本重试。
    if "can't parse entities" in (resp.text or "").lower():
        fallback_payload = {
            "chat_id": TG_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        }
        fallback_resp = requests.post(url, json=fallback_payload, timeout=30)
        if fallback_resp.ok:
            print("[OK] Telegram 推送成功（fallback: plain text）")
            return True

        print(f"[ERROR] Telegram fallback 推送失败: {fallback_resp.status_code} {fallback_resp.text}")
        return False

    print(f"[ERROR] Telegram 推送失败: {resp.status_code} {resp.text}")
    return False


def escape_markdown_v2(value: str) -> str:
    text = str(value or "")
    text = text.replace("\\", "\\\\")
    for ch in TG_MD_V2_SPECIALS:
        text = text.replace(ch, f"\\{ch}")
    return text


def render_template(template: str, variables: dict) -> str:
    """安全地渲染模板，未匹配的变量保持原样。"""
    text = template
    for key, value in variables.items():
        # 用户输入和 release body 等动态内容统一做 MarkdownV2 转义。
        safe_value = escape_markdown_v2(value)
        text = text.replace(f"{{{key}}}", safe_value)
    return text.strip()


# ───────────────────── 获取器 ─────────────────────

def fetch_releases(repo: str, include_prerelease: bool = False) -> list[dict]:
    """获取最新的 releases（最多 10 条）。"""
    url = f"{GITHUB_API}/repos/{repo}/releases"
    resp = requests.get(url, headers=gh_headers(), params={"per_page": 10}, timeout=30)
    resp.raise_for_status()
    releases = resp.json()
    if not include_prerelease:
        releases = [r for r in releases if not r.get("prerelease")]
    results = []
    for r in releases:
        results.append({
            "id": str(r["id"]),
            "tag": r.get("tag_name", ""),
            "url": r.get("html_url", ""),
            "body": textwrap.shorten(r.get("body") or "", width=500, placeholder="…"),
            "name": r.get("name") or r.get("tag_name", ""),
            "prerelease": r.get("prerelease", False),
            "created_at": r.get("published_at") or r.get("created_at", ""),
        })
    return results


def fetch_tags(repo: str) -> list[dict]:
    """获取最新的 tags。"""
    url = f"{GITHUB_API}/repos/{repo}/tags"
    resp = requests.get(url, headers=gh_headers(), params={"per_page": 10}, timeout=30)
    resp.raise_for_status()
    results = []
    for t in resp.json():
        sha = t["commit"]["sha"]
        results.append({
            "id": sha,
            "tag": t["name"],
            "url": f"https://github.com/{repo}/releases/tag/{t['name']}",
            "sha": sha,
            "sha_short": sha[:7],
        })
    return results


def fetch_commits(repo: str, branch: str = "") -> list[dict]:
    """获取默认 / 指定分支的最新 commits。"""
    url = f"{GITHUB_API}/repos/{repo}/commits"
    params = {"per_page": 10}
    if branch:
        params["sha"] = branch
    resp = requests.get(url, headers=gh_headers(), params=params, timeout=30)
    resp.raise_for_status()
    results = []
    for c in resp.json():
        sha = c["sha"]
        results.append({
            "id": sha,
            "sha": sha,
            "sha_short": sha[:7],
            "message": c["commit"]["message"].split("\n")[0],
            "url": c["html_url"],
            "author": c["commit"]["author"]["name"],
            "date": c["commit"]["author"]["date"],
            "branch": branch or "(default)",
        })
    return results


# ───────────────────── 主逻辑 ─────────────────────

def check_subscription(sub: dict, defaults: dict, state: dict) -> dict:
    """检查单个订阅，推送新事件，返回更新后的 state 片段。"""
    repo = sub["repo"]
    mode = sub.get("mode", "release")
    state_key = f"{repo}:{mode}"
    seen: set = set(state.get(state_key, []))

    print(f"\n── 检查 {repo} [{mode}] ──")

    is_first_run = state_key not in state

    # 获取事件列表
    if mode == "release":
        items = fetch_releases(repo, sub.get("include_prerelease", False))
    elif mode == "tag":
        items = fetch_tags(repo)
    elif mode == "commit":
        items = fetch_commits(repo, sub.get("branch", ""))
    else:
        print(f"[WARN] 未知 mode: {mode}，跳过")
        return {}

    # 确定模板
    template = sub.get("template") or defaults.get("templates", {}).get(mode, "{repo} 有新事件: {url}")

    new_items = [i for i in items if i["id"] not in seen]
    if not new_items:
        print("  没有新事件")
        return {}

    # 首次和后续运行都只推送最新版本
    if is_first_run:
        push_items = new_items[:1]  # 只推最新的那个
        print("  首次运行，推送最新版本")
    else:
        push_items = new_items[:1]  # 后续也只推最新的那个
        print(f"  发现 {len(new_items)} 条新事件，仅推送最新 1 条")

    for item in reversed(push_items):  # 按时间正序推送
        variables = {"repo": repo, **item}
        text = render_template(template, variables)
        if send_telegram(text):
            seen.add(item["id"])

    return {state_key: list(seen)}


def main():
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[FATAL] 请设置 TG_BOT_TOKEN 和 TG_CHAT_ID 环境变量")
        sys.exit(1)

    config = load_config()
    state = load_state()
    defaults = config.get("defaults", {})
    subs = config.get("subscriptions", [])

    if not subs:
        print("[WARN] subscriptions.yaml 中没有订阅项")
        return

    for sub in subs:
        try:
            updates = check_subscription(sub, defaults, state)
            state.update(updates)
        except Exception as e:
            print(f"[ERROR] {sub.get('repo', '?')}: {e}")

    save_state(state)
    print("\n✅ 检查完成，state 已保存")


if __name__ == "__main__":
    main()
