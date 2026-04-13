# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common
use conda code2Doc env

## Project Overview

Knowledge Base Service (代码知识底座管理服务) - A Python service that parses code repositories, builds knowledge graphs (structure + dependency + semantic), and provides semantic search capabilities for documentation generation agents.

## Tech Stack

- **Python 3.11+**
- **FastAPI** - Web framework
- **Neo4j** - Graph database for code relationships
- **Milvus** - Vector database for semantic search
- **Tree-sitter** - Code parsing for multiple languages
- **LangChain** - LLM and embedding model integration
- **MCP** - Model Context Protocol server for AI agent integration

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the service
uvicorn app.main:app --reload

# Run tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run a single test file
pytest tests/unit/test_file.py -v

# Run a specific test
pytest tests/unit/test_file.py::test_function -v

# Code formatting
black app/ tests/
ruff check app/ tests/
```

## Architecture

### Pipeline-Based Processing

The core processing is a sequential pipeline with stages defined in `STAGE_ORDER` (see `app/domain/models/pipeline.py`):

1. **structure_graph_build** - Scan repository, parse code with Tree-sitter, and build structure graph in Neo4j (merged stage)
2. **dependency_graph_build** - Build dependency graph in Neo4j
3. **semantic_analysis** - Generate summaries for code nodes
4. **module_detection** - Detect functional modules and build semantic graph in Neo4j
5. **vector_db_store** - Extract content, generate embeddings, and store in Milvus

**Note**:
- `repo_traversal`, `code_parsing` and `symbol_extraction` have been merged into `structure_graph_build`
- `semantic_graph_build` has been merged into `module_detection`
- `embedding_generation` has been merged into `vector_db_store`

The stages now parse/process code files immediately before storing nodes in Neo4j, keeping only node IDs in context rather than full parsed results. This reduces memory usage and simplifies the data flow.

### Key Architectural Components

**Pipeline Orchestrator** (`app/core/pipeline.py`):
- `PipelineOrchestrator` manages stage execution
- Each stage implements `PipelineStageHandler` base class
- Supports pause/resume via context persistence to JSON logs
- Stage results stored in `PipelineContext` with full execution history

**PipelineContext** (`app/domain/models/pipeline.py`):
- Mutable state container passed through all stages
- Stores stage results in `stages: Dict[PipelineStage, StageResult]`
- Shared data in `data: Dict[str, Any]` dictionary
- Persisted to `./log/{repo_id}/` for recovery

**Graph Models** (`app/domain/models/graph.py`):
- `Repository`, `Directory`, `File` - Structural nodes
- `Class`, `Method` - Code symbol nodes
- `Module`, `Workflow` - Semantic abstraction nodes
- All nodes extend `BaseNode` with `to_dict()` for Neo4j serialization

**Database Clients** (`app/infrastructure/db/`):
- `Neo4jClient` - Singleton async client with `execute_query()` method
- `MilvusClient` - Vector database operations

**Dual Interface**:
- **REST API** (`app/api/routes/`) - HTTP endpoints for pipeline control
- **MCP Server** (`app/mcp/`) - Tools for AI agents (8 tools: search_nodes, get_modules, etc.)

## Project Structure

```
app/
├── api/routes/           # FastAPI routers (initialization, progress)
├── core/                 # Pipeline orchestration
│   ├── pipeline.py       # PipelineOrchestrator
│   ├── pipeline_logger.py # Context persistence
│   └── stages/           # Stage handlers (11 stages)
├── domain/               # Domain layer
│   ├── models/           # Data models (pipeline, graph, vector)
│   ├── parser/           # Tree-sitter parsers
│   ├── analyzer/         # Code analyzers
│   └── llm/              # LLM client abstractions
├── infrastructure/       # Infrastructure layer
│   ├── db/               # Neo4j and Milvus clients
│   └── csv_storage.py    # Status persistence
├── mcp/                  # MCP server implementation
│   ├── server.py         # MCP server setup
│   └── tools.py          # Tool implementations
├── utils/                # Utilities
├── config.py             # Pydantic settings (.env based)
└── main.py               # FastAPI application factory
```

## Configuration

Environment variables from `.env` (see `.env.example`):

```bash
# Core services
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
MILVUS_HOST=localhost
MILVUS_PORT=19530

# LLM Provider: "qwen" | "openai" | "anthropic"
LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=your-key

# Pipeline
BATCH_SIZE=100
MAX_RETRIES=3
```

## Pipeline Stage Implementation

When implementing a new stage:

1. Create class in `app/core/stages/{stage_name}.py`
2. Extend `PipelineStageHandler` and set `stage` attribute
3. Implement `async def execute(self, context: PipelineContext) -> StageResult`
4. Read inputs from `context.data` (populated by previous stages)
5. Store outputs in `context.data` for subsequent stages
6. Return `StageResult` with status, message, and metadata
7. Register in `app/main.py:_register_pipeline_stages()`

Example pattern:
```python
class MyStage(PipelineStageHandler):
    stage = PipelineStage.MY_STAGE

    async def execute(self, context: PipelineContext) -> StageResult:
        # Read from previous stages
        files = context.data.get("files", [])

        # Process...
        result = await process_files(files)

        # Store for next stages
        context.data["my_result"] = result

        return StageResult(
            stage=self.stage,
            status=PipelineStatus.COMPLETED,
            message=f"Processed {len(result)} items",
            metadata={"count": len(result)},
        )
```

## Testing

- **Unit tests**: `tests/unit/` - Test individual components with mocks
- **Integration tests**: `tests/integration/` - Test with real database connections
- Uses `pytest-asyncio` for async test support
- Configured in `pytest.ini` with `asyncio_mode = auto`

## Important Patterns

**Context Data Flow**: Each stage reads from and writes to `context.data` dictionary. Common keys:
- `"traversal_result"` - Repository traversal result with files and directories
- `"node_ids"` - Node ID references after structure graph build (replaces parsed_results)
  - `repository_id`, `directory_ids`, `file_ids`, `class_ids`, `method_ids`
- `"embeddings"` - Vector embeddings for code snippets

**Note**: After the architecture change, stages should query Neo4j using node IDs rather than reading full data from context.

**Error Handling**: Stages return `StageResult(status=PipelineStatus.FAILED)` on error; pipeline stops on first failure. Orchestrator logs all stage transitions.

**Singleton Pattern**: `get_orchestrator()`, `get_neo4j_client()`, `get_milvus_client()` all return singleton instances.

**Status Persistence**: Repository initialization status stored in CSV (`./log/repo_status.csv`) for quick lookups without parsing log files.

**Logging**: Pipeline events logged as JSON Lines to `./log/{repo_id}/pipeline.log` for structured parsing and context recovery.
