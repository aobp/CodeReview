# AI Code Review Agent

An autonomous agent-based code review system that analyzes Git PR diffs using a combination of static analysis tools and LLM agents. The system uses a ReAct (Reasoning + Acting) pattern, allowing the agent to autonomously decide which tools to use and when to generate comprehensive code reviews.

## Architecture

The system follows a modular, layered architecture with extensible DAO (Data Access Object) layer:

```
dao/             # DAO layer: Extensible storage backends (file, SQL, NoSQL ready)
assets/          # Asset layer: Code analysis and indexing (AST, RepoMap, CPG)
tools/           # Tool layer: MCP-compliant tools that wrap Asset queries
core/            # Core layer: Configuration, LLM clients, and Shared State
agents/          # Agent layer: Autonomous ReAct agent with LangGraph
main.py          # Entry point
log/             # Log directory: Agent observations and tool call logs
```

### Key Components

- **DAO Layer**: Extensible storage abstraction supporting file-based storage (MVP) with interfaces ready for SQL/NoSQL backends
- **Assets**: Code analysis artifacts (RepoMap, AST, CPG) persisted via DAO
- **Tools**: MCP-compliant tools (FetchRepoMapTool, ReadFileTool) that agents can use
- **ReAct Agent**: Autonomous agent that reasons about code and acts using available tools

## Tech Stack

- **Python 3.10+**
- **LangGraph**: Agent orchestration using StateGraph and Nodes
- **Pydantic v2**: Data validation for all Agent I/O and Asset schemas
- **Tree-sitter**: Code parsing (planned for future versions)

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. For OpenAI or DeepSeek provider (optional):
```bash
pip install openai
```

3. Configure DeepSeek (if using):
   - Set `DEEPSEEK_API_KEY` environment variable in your `~/.zshrc`:
     ```bash
     export DEEPSEEK_API_KEY="your-deepseek-api-key"
     ```
   - Or configure in `config.yaml`:
     ```yaml
     llm:
       provider: "deepseek"
       model: "deepseek-chat"
       api_key: "your-api-key"
       base_url: "https://api.deepseek.com"
     ```

## Usage

### Command Line Interface

The CLI supports two modes for getting diff content:

#### Mode 1: Git Branch Mode (Recommended)

Compare two Git branches using triple-dot syntax:

```bash
# Compare feature-x branch with main
python main.py --repo ./project --base main --head feature-x

# Compare current HEAD with main (default head is HEAD)
python main.py --repo ./project --base main
```

#### Mode 2: Local Diff File Mode

Use a pre-generated diff file:

```bash
python main.py --repo ./project --diff ./changes.diff
```

### Command Line Options

- `--repo` (required): Path to the repository to review
- `--base`: Target branch for Git diff mode (e.g., 'main', 'master')
- `--head`: Source branch or commit for Git diff mode (default: 'HEAD')
- `--diff`: Path to a local .diff file (alternative to --base/--head)
- `--output`: Path to save review results JSON (default: review_results.json)

**Note**: If both `--diff` and `--base` are provided, `--diff` takes priority.

### Example: Testing with Sentry Repository

```bash
# Git branch mode
python main.py \
  --repo /Users/wangyue/Code/CodeReviewData/ReviewDataset/sentry-greptile \
  --base performance-optimization-baseline \
  --head performance-enhancement-complete

# Or generate diff file first, then use file mode
cd /Users/wangyue/Code/CodeReviewData/ReviewDataset/sentry-greptile
git diff performance-optimization-baseline...performance-enhancement-complete > /tmp/changes.diff
cd /Users/wangyue/Code/CodeReview
python main.py --repo /Users/wangyue/Code/CodeReviewData/ReviewDataset/sentry-greptile --diff /tmp/changes.diff
```

See [QUICK_START.md](QUICK_START.md) for more examples and VS Code debugging setup.

### Programmatic Usage

```python
import asyncio
from core.config import Config
from agents.bot import run_react_agent

async def review_code():
    config = Config.load_default()
    
    pr_diff = """your git diff here"""
    
    results = await run_react_agent(
        pr_diff=pr_diff,
        config=config
    )
    
    print(f"Found {len(results['identified_issues'])} issues")
    for issue in results['identified_issues']:
        print(f"{issue['file']}:{issue['line']} - {issue['message']}")

asyncio.run(review_code())
```

## Workflow

The system uses an autonomous ReAct (Reasoning + Acting) agent that follows this workflow:

1. **Initialize Storage**: DAO layer is initialized (file-based storage for MVP)
2. **Build Assets**: Repository map is built and persisted if not already available
3. **Agent Reasoning**: Agent analyzes the PR diff and autonomously decides:
   - Whether to use tools or not
   - Which tools to use and when
   - When enough information is gathered
4. **Tool Execution**: Agent may use:
   - `fetch_repo_map`: Understand project structure
   - `read_file`: Examine specific files from the diff
5. **Review Generation**: Agent generates comprehensive review with structured issues
6. **Logging**: All observations and tool calls are automatically logged to `log/repo/model/timestamp/observations.log`

### Agent Autonomy

The agent has full autonomy to:
- Skip tool calls if not needed
- Retry failed tool calls (with failure tracking)
- Provide fallback reviews when approaching iteration limits
- Make decisions based on context and previous observations

## Configuration

Edit `core/config.py` or create a custom config:

```python
from core.config import Config, LLMConfig

config = Config(
    llm=LLMConfig(
        provider="openai",  # or "mock" for testing
        model="gpt-4",
        api_key="your-api-key"
    )
)
```

## Features

### Core Features

- ✅ **Autonomous ReAct Agent**: Self-directed agent that decides tool usage and review strategy
- ✅ **Extensible DAO Layer**: File-based storage (MVP) with interfaces ready for SQL/NoSQL/GraphDB backends
- ✅ **Asset Management**: RepoMap builder with automatic DAO persistence (idempotent builds)
- ✅ **MCP-Compliant Tools**: Standardized tool interface (FetchRepoMapTool, ReadFileTool)
- ✅ **Comprehensive Logging**: Automatic logging of agent observations and tool calls to structured log files
- ✅ **Multiple LLM Providers**: Support for OpenAI, DeepSeek, and mock provider (for testing)
- ✅ **Error Handling**: Graceful degradation with detailed error reporting
- ✅ **Type Safety**: Full type hints and Pydantic v2 validation

### Logging

Agent observations and tool calls are automatically saved to:
```
log/
  └── {repo_name}/
      └── {model_name}/
          └── {timestamp}/
              └── observations.log
```

Each log file contains:
- All agent observations (reasoning steps)
- All tool calls (input parameters and results)
- Metadata (repository, model, timestamp)

## Project Structure

```
CodeReview/
├── dao/                    # Data Access Object layer
│   ├── base.py            # BaseStorageBackend interface
│   ├── factory.py          # Storage factory (singleton pattern)
│   └── backends/
│       └── local_file.py   # File-based storage implementation
├── assets/                 # Asset builders
│   ├── base.py             # BaseAssetBuilder interface
│   └── implementations/
│       └── repo_map.py     # RepoMap builder
├── tools/                  # MCP-compliant tools
│   ├── base.py             # BaseTool interface
│   ├── repo_tools.py       # FetchRepoMapTool
│   └── file_tools.py       # ReadFileTool
├── agents/                 # Agent implementations
│   └── bot.py              # ReAct agent
├── core/                   # Core utilities
│   ├── config.py           # Configuration management
│   ├── llm.py              # LLM provider abstraction
│   └── state.py            # LangGraph state definitions
├── log/                    # Agent logs (auto-generated)
├── .storage/               # DAO storage directory (auto-generated)
├── main.py                 # Entry point
└── config.yaml             # Configuration file
```

## Future Enhancements

- [ ] Tree-sitter integration for AST analysis
- [ ] Control Flow Graph (CPG) generation
- [ ] SQL/NoSQL/GraphDB storage backends
- [ ] Real GitHub API integration
- [ ] Vector store for code embeddings
- [ ] Advanced query capabilities
- [ ] Web UI for review results
- [ ] CI/CD integration

## Development

### Coding Standards

The project follows strict coding standards:

- **Type Hints**: Mandatory for all functions and methods
- **Docstrings**: Google-style for all classes and public methods
- **Async IO**: All IO-bound operations use async/await
- **Error Handling**: Agents never crash; errors are returned in results
- **Dependency Injection**: No hardcoded dependencies; use DI patterns
- **Abstract Interfaces**: All major components use ABC interfaces

### Design Principles

- **High Cohesion, Low Coupling**: Modular architecture with clear boundaries
- **Extensibility**: Easy to add new storage backends, tools, and agents
- **Idempotency**: Asset building and operations are idempotent
- **Observability**: Comprehensive logging for debugging and monitoring

### Testing

For testing without API keys, use the mock LLM provider:

```python
config = Config(
    llm=LLMConfig(provider="mock")
)
```

## License

[Add your license here]

