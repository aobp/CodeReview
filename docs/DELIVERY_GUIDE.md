# 开源项目交付说明（安装 / 配置 / 使用）

适用场景：
- 本地 CLI 审查（`main.py`）
- GitHub PAT Webhook 服务（`github_pat/`，PR 评论触发）

## 1. 安装

基础环境：
- Conda（Miniconda/Anaconda）
- Python 3.13（必须）
- git

安装依赖（Conda）：
```bash
conda create -n codereview python=3.13 -y
conda activate codereview
python -m pip install -U pip
pip install -r requirements.txt
```

可选外部工具（用于语法检查，未安装会自动跳过）：
- Python: `ruff`
- TypeScript/JavaScript: `biome`
- Go: `go vet`（随 Go 自带）
- Java: `pmd`
说明：这些工具仅用于语法/静态检查，缺失时系统会自动跳过该语言的检查，不影响主流程运行；安装命令见文末。

## 2. 配置（重点：环境变量）

### 2.1 LLM 配置（所有模式必需）

推荐用环境变量，避免把 key 写进配置文件：
```bash
export LLM_API_KEY="your-llm-api-key"
```
优先级规则：`LLM_API_KEY` > provider 专用 key（`DEEPSEEK_API_KEY` / `ZHIPUAI_API_KEY`）。注意、provider 专用 key 在 config.py L210行处

### 2.2 config.yaml

仓库根目录已提供 `config.yaml`，你可以保持默认值直接运行。

最小改动：
- `llm.provider`
- `llm.model`

其余字段保持默认即可。

### 2.3 GitHub PAT Webhook 服务（.env） （本地运行不需要管）

示例文件：`.env.github_pat.example`。复制为 `.env` 并填写：
```bash
cp .env.github_pat.example .env
set -a; source .env; set +a
```

最小必填项（Webhook 服务必须）：
- `GITHUB_TOKEN`
- `GITHUB_WEBHOOK_SECRET`
- `ALLOWED_REPOS`

其余变量保持默认即可运行。

## 3. 使用

### 3.1 CLI 方式（本地审查）

```bash
python main.py --repo /path/to/repo --base main --head feature-x
```

输在 `log/` 目录：
- `review_results.json`
- 对话历史信息

### 3.2 GitHub PAT Webhook 服务

启动服务：
```bash
uvicorn github_pat.app:app --host 0.0.0.0 --port 8000
```

配置 GitHub Webhook（每个仓库都要设置）：
- Payload URL：`https://<your-domain>/github/webhook`
- Content type：`application/json`
- Secret：与 `.env` 的 `GITHUB_WEBHOOK_SECRET` 一致
- Events：`Issue comments`

触发方式：
- 在 PR Conversation 评论：`@cptbot review`

权限自检（可选）：
```bash
set -a; source .env; set +a
OWNER=owner REPO=repo PR_NUMBER=123 bash docs/check_pat.sh
```

## 4. 可选依赖与特性

## 5. 常见问题

- 启动时报 `api_key client option must be set`：未配置 `LLM_API_KEY` / `LLM_PROVIDER`
- PAT 403：Token 权限不足，执行 `docs/check_pat.sh` 自检
- `config.yaml` 未生效：缺少 `pyyaml` 或配置文件格式错误

## 6. 可选工具安装命令（集中）

Python（ruff）：
```bash
pip install ruff
```

TypeScript/JavaScript（biome）：
```bash
npm install -g @biomejs/biome
```

Go（go vet）：
```bash
go version
```

Java（pmd）：
```bash
brew install pmd
```
