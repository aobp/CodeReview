# 开源项目交付说明（安装 / 配置 / 使用）

适用场景：
- 本地 CLI 审查（`main.py`）
- GitHub PAT Webhook 服务（`github_pat/`，PR 评论触发）

## 1. 安装

基础环境：
- Python 3.10+
- git

安装依赖：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

可选外部工具（用于语法检查，未安装会自动跳过）：
- Python: `ruff`
- TypeScript/JavaScript: `biome`
- Go: `go vet`（随 Go 自带）
- Java: `pmd`

## 2. 配置（重点：环境变量）

### 2.1 LLM 配置（所有模式必需）

推荐用环境变量，避免把 key 写进配置文件：
```bash
export LLM_PROVIDER="deepseek"  # openai / deepseek / zhipuai
export LLM_API_KEY="your-llm-api-key"
export LLM_MODEL="deepseek-chat"  # 可选
export LLM_BASE_URL="https://api.deepseek.com"  # 可选（OpenAI 兼容 API）
```

优先级规则：`LLM_API_KEY` > provider 专用 key（`DEEPSEEK_API_KEY` / `ZHIPUAI_API_KEY`）。

### 2.2 config.yaml（可选，默认可不改）

仓库根目录已提供 `config.yaml`，你可以保持默认值直接运行。

最小改动（仅当你不想用环境变量时）：
- `llm.provider`
- `llm.model`
- `llm.api_key`

其余字段保持默认即可。

### 2.3 GitHub PAT Webhook 服务（.env）

示例文件：`.env.github_pat.example`。复制为 `.env` 并填写：
```bash
cp .env.github_pat.example .env
set -a; source .env; set +a
```

最小必填项（Webhook 服务必须）：
- `GITHUB_TOKEN`
- `GITHUB_WEBHOOK_SECRET`
- `ALLOWED_REPOS`
- `LLM_PROVIDER`
- `LLM_API_KEY`

其余变量保持默认即可运行。

### 2.4 最小改动清单

CLI 模式：
- 设置 `LLM_PROVIDER` + `LLM_API_KEY`
- `config.yaml` 保持默认即可

Webhook 服务模式：
- 在 `.env` 中填写 `GITHUB_TOKEN` / `GITHUB_WEBHOOK_SECRET` / `ALLOWED_REPOS`
- 同时填写 `LLM_PROVIDER` / `LLM_API_KEY`
- 其余项全部保留默认值

## 3. 使用

### 3.1 CLI 方式（本地审查）

```bash
python main.py --repo /path/to/repo --base main --head feature-x
```

输出：
- 默认生成 `review_results.json`
- 详细日志在 `log/` 目录

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

建议安装（否则相关功能会降级）：
- `pyyaml`：加载 `config.yaml`
- `python-dotenv`：自动读取 `.env`

Lite-CPG 多语言支持（可选）：
- `tree-sitter-languages`
- `tree-sitter-go` / `tree-sitter-java` / `tree-sitter-javascript` / `tree-sitter-ruby`

## 5. 常见问题

- 启动时报 `api_key client option must be set`：未配置 `LLM_API_KEY` / `LLM_PROVIDER`
- Webhook 401：`GITHUB_WEBHOOK_SECRET` 不一致，或未设置 `ALLOW_UNSIGNED_WEBHOOKS=1`（仅限本地调试）
- PAT 403：Token 权限不足，执行 `docs/check_pat.sh` 自检
- `config.yaml` 未生效：缺少 `pyyaml` 或配置文件格式错误
