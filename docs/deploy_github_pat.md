# GitHub PAT Webhook 部署（FastAPI）

目标：在 GitHub PR 的普通评论里输入 `@cptbot review`，触发本服务全自动跑审查，并以 **PR Review 行内评论** 形式回贴 RiskItem。

## 1. 前置条件

- 一台能访问 GitHub 的服务器（或本机测试）
- 已安装：`git`、Conda（Miniconda/Anaconda）
- 你的 LLM 配置（`config.yaml` + API key 环境变量）已可跑通 `python main.py --repo ...`

## 2. 安装依赖（Conda）

在本项目目录：

```bash
conda create -n codereview python=3.13 -y
conda activate codereview
python -m pip install -U pip
pip install -r requirements.txt
```

新增的依赖包含：`fastapi`、`uvicorn`、`httpx`。

## 3. 创建 PAT

公有仓库场景推荐 fine-grained PAT：

- Repository access：选择你的 5 个目标仓库
- Permissions：
  - Contents: Read
  - Pull requests: Read & write
  - Issues: Read & write（用于回贴评论/Review）

把 token 保存为环境变量 `GITHUB_TOKEN`。

## 4. 配置环境变量

本项目默认不会提交 `.env`（已在 `.gitignore` 中忽略），你可以自己创建：

- 复制示例：`cp .env.github_pat.example .env` 并填写
- 在 mac/zsh 下让当前终端加载：`set -a; source .env; set +a`

核心变量：

- `GITHUB_TOKEN`：PAT
- `GITHUB_WEBHOOK_SECRET`：Webhook secret（用于验签）
- `ALLOWED_REPOS`：仓库白名单，逗号分隔，例如：`owner1/repo1,owner2/repo2`

可选变量（有默认值）：

- `BOT_TRIGGER`：默认 `@cptbot review`
- `MAX_CONCURRENT_JOBS`：默认 `2`
- `COOLDOWN_SECONDS`：默认 `60`（同一 PR 短时间重复触发会被去重）
- `MAX_REVIEW_COMMENTS`：默认 `50`
- `KEEP_WORKTREE`：默认 `0`（任务结束清理 worktree；mirror 永久保留）
- `MIRROR_ROOT`/`WORK_ROOT`/`DB_PATH`：默认都在 `.storage/github_pat/`
- `ENABLE_REPOMAP`/`ENABLE_LITE_CPG`/`ENABLE_LINT`：默认 `1`

## 5. 启动服务

在 conda 环境里启动：

```bash
conda activate codereview
uvicorn github_pat.app:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://localhost:8000/healthz
```

## 6. 配置 GitHub Webhook（每个仓库）

仓库 Settings → Webhooks → Add webhook：

- Payload URL：`https://<your-domain>/github/webhook`
- Content type：`application/json`
- Secret：填写 `GITHUB_WEBHOOK_SECRET`
- Which events：选择 **Issue comments**

完成后，在 PR Conversation 下评论：

```
@cptbot review
```

## 7. 多 PR 只 clone 一次（mirror + worktree）

服务端对每个 `owner/repo` 维护一个永久 mirror：

- `.storage/github_pat/mirrors/{owner}/{repo}.git`

每次触发只会：

- `git fetch` 更新 mirror（有 repo 级锁）
- `git worktree add` 创建独立 PR 工作区运行审查
- 审查结束删除 worktree（默认），mirror 不删除

## 8. 本地测试（可选）

GitHub webhook 不能直接打到 localhost，推荐：

- `ngrok http 8000`，然后把 webhook URL 配成 ngrok 的公网地址

开发调试时可临时跳过验签（不建议用于线上）：

```bash
export ALLOW_UNSIGNED_WEBHOOKS=1
```

## 9. 线上部署建议（systemd，可选）

示例 `/etc/systemd/system/codereview-github-pat.service`（用 conda env 的 python 路径）：

```ini
[Unit]
Description=AI Code Review GitHub PAT Webhook
After=network.target

[Service]
WorkingDirectory=/path/to/CodeReview
Environment=GITHUB_TOKEN=xxx
Environment=GITHUB_WEBHOOK_SECRET=xxx
Environment=ALLOWED_REPOS=owner1/repo1,owner2/repo2
ExecStart=/opt/miniconda3/envs/codereview/bin/python -m uvicorn github_pat.app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now codereview-github-pat
sudo systemctl status codereview-github-pat
```

## 10. PAT 权限自检（纯本地，不依赖 webhook 回调）

用脚本快速确认 fine-grained PAT 是否具备“读 PR + 发评论（issues comments）”权限：

```bash
set -a; source .env; set +a

OWNER=owner REPO=repo PR_NUMBER=123 bash docs/check_pat.sh
```

可选：同时检查是否能创建 PR Review（会在 PR 上留下一个 review，不自动删除）：

```bash
set -a; source .env; set +a

CHECK_REVIEW=1 OWNER=owner REPO=repo PR_NUMBER=123 bash docs/check_pat.sh
```
