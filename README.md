# AI Code Review Agent (MVP)

An agent-based code review system that analyzes Git PR diffs using a combination of static analysis tools and LLM agents.

## Architecture

The system follows a modular, layered architecture:

```
assets/          # Asset layer: Code analysis and indexing (AST, RepoMap, CPG)
tools/           # Tool layer: MCP-compliant tools that wrap Asset queries
core/            # Core layer: Configuration, LLM clients, and Shared State
agents/          # Decision layer: LangGraph workflows, nodes, and state definitions
interface/       # Interface layer: User-facing interfaces (CLI, API, etc.)
main.py          # Entry point
```

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

### Basic Usage

Run the code review agent with a sample diff:

```bash
python main.py
```

### Programmatic Usage

```python
import asyncio
from core.config import Config
from agents.workflow import run_review_workflow

async def review_code():
    config = Config.load_default()
    
    pr_diff = """your git diff here"""
    repo_map_summary = """repository structure summary"""
    
    results = await run_review_workflow(
        pr_diff=pr_diff,
        repo_map_summary=repo_map_summary,
        config=config
    )
    
    print(f"Found {len(results['identified_issues'])} issues")
    for issue in results['identified_issues']:
        print(f"{issue['file']}:{issue['line']} - {issue['message']}")

asyncio.run(review_code())
```

## Workflow

The system follows this workflow:

1. **Manager Node**: Analyzes the PR diff and repository map to identify focus files
2. **Reviewer Node**: Reviews the focus files and generates detailed comments
3. **Output**: Returns structured review results with issues and suggestions

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

## MVP Features

- ✅ Modular architecture with ABC interfaces
- ✅ LangGraph workflow (Manager → Reviewer)
- ✅ RepoMap builder (file tree generation)
- ✅ File reading and search tools
- ✅ Mock LLM provider (no API key required for testing)
- ✅ Error handling and graceful degradation

## Future Enhancements

- [ ] Tree-sitter integration for AST analysis
- [ ] Control Flow Graph (CPG) generation
- [ ] Real GitHub API integration
- [ ] Vector store for code embeddings
- [ ] Advanced query capabilities

## Development

The project follows strict coding standards:

- **Type Hints**: Mandatory for all functions and methods
- **Docstrings**: Google-style for all classes and public methods
- **Async IO**: All IO-bound operations use async/await
- **Error Handling**: Agents never crash; errors are returned in results

## License

[Add your license here]

