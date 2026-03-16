# 代码知识底座管理服务设计方案

## 一、设计目标

构建一个可扩展、可恢复的代码知识底座管理服务，将代码仓库解析为三层图结构（结构图、依赖图、语义图），并提供向量化的语义检索能力，为文档生成服务提供数据支持。

## 二、系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        代码知识底座管理服务                               │
│                           (FastAPI + Python 3.11)                        │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   API 层     │  │  Pipeline层  │  │   存储层     │  │   MCP层      │ │
│  │  (REST API)  │  │ (构建流水线)  │  │(Neo4j+Milvus)│  │  (Tools)     │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
│         │                 │                 │                 │         │
│         ▼                 ▼                 ▼                 ▼         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      领域层 (Domain Layer)                       │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │   │
│  │  │ CodeParser│ │SymbolExtractor│ │DependencyAnalyzer│ │LLMProcessor│ │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘ │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      外部依赖                                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │  Neo4j     │  │   Milvus   │  │    LLM     │  │  Tree-sitter/Clang│  │
│  │  (图数据库) │  │  (向量库)   │  │  (语义分析) │  │   (代码解析)      │  │
│  └────────────┘  └────────────┘  └────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块划分

```
knowledge_base_service/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── initialization.py  # 初始化相关API
│   │   │   └── progress.py        # 进度查询API
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── requests.py        # 请求模型
│   │       └── responses.py       # 响应模型
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pipeline.py            # 流水线编排器
│   │   ├── pipeline_state.py      # 流水线状态管理
│   │   └── events.py              # 事件系统
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── graph.py           # 图模型定义
│   │   │   └── vector.py          # 向量模型定义
│   │   ├── parser/
│   │   │   ├── __init__.py
│   │   │   ├── code_parser.py     # 代码解析器接口
│   │   │   ├── tree_sitter_parser.py
│   │   │   └── language_factory.py
│   │   ├── analyzer/
│   │   │   ├── __init__.py
│   │   │   ├── symbol_extractor.py    # 符号提取
│   │   │   ├── dependency_analyzer.py # 依赖分析
│   │   │   └── semantic_analyzer.py   # 语义分析
│   │   └── llm/
│   │       ├── __init__.py
│   │       ├── client.py          # LLM客户端
│   │       ├── prompts.py         # 提示词模板
│   │       └── embedding.py       # 向量化服务
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── neo4j_client.py    # Neo4j 客户端
│   │   │   ├── milvus_client.py   # Milvus 客户端
│   │   │   └── repositories.py    # 数据访问层
│   │   └── storage/
│   │       ├── __init__.py
│   │       └── repo_storage.py    # 仓库文件存储
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py              # MCP 服务器
│   │   └── tools.py               # MCP 工具定义
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── tests/
├── requirements.txt
└── Dockerfile
```

## 三、数据模型设计

### 3.1 图数据库模型 (Neo4j)

#### 节点标签
```cypher
// Repository 节点
(:Repository {
    id: string,
    name: string,
    type: "Repository",
    description: string,
    extra: json,
    path: string,
    created_at: datetime,
    updated_at: datetime
})

// Directory 节点
(:Directory {
    id: string,
    name: string,
    type: "Directory",
    description: string,
    extra: json,
    path: string
})

// File 节点
(:File {
    id: string,
    name: string,
    type: "File",
    description: string,
    extra: json,
    path: string,
    summary: string,
    embeddingId: string,
    fileType: string,  // code / doc / config
    suffix: string
})

// Class 节点
(:Class {
    id: string,
    name: string,
    type: "Class",
    description: string,
    extra: json,
    filePath: string,
    startLine: int,
    endLine: int,
    language: string,
    code: string,
    summary: string,
    embeddingId: string,
    docstring: string
})

// Method 节点
(:Method {
    id: string,
    name: string,
    type: "Method",
    description: string,
    extra: json,
    filePath: string,
    startLine: int,
    endLine: int,
    language: string,
    code: string,
    summary: string,
    embeddingId: string,
    docstring: string
})

// Module 节点
(:Module {
    id: string,
    name: string,
    type: "Module",
    description: string,
    extra: json,
    summary: string,
    detail: string,
    keywords: [string],
    confidence: float,
    embeddingId: string
})

// Workflow 节点
(:Workflow {
    id: string,
    name: string,
    type: "Workflow",
    description: string,
    extra: json,
    summary: string,
    detail: string,
    keywords: [string],
    confidence: float,
    embeddingId: string
})
```

#### 关系类型
```cypher
// 结构关系
(:Repository)-[:CONTAIN]->(:Directory)
(:Directory)-[:CONTAIN]->(:File)
(:Directory)-[:CONTAIN]->(:Directory)
(:File)-[:CONTAIN]->(:Class)
(:Class)-[:CONTAIN]->(:Method)

// 依赖关系
(:Method)-[:CALL]->(:Method)
(:Class)-[:INHERIT]->(:Class)
(:Class)-[:IMPLEMENT]->(:Class)  // 接口实现
(:File)-[:USE]->(:File)
(:Method)-[:USE]->(:Class)

// 归属关系
(:File)-[:BELONG_TO]->(:Module)
(:Class)-[:BELONG_TO]->(:Module)
(:Method)-[:BELONG_TO]->(:Module)
(:Workflow)-[:BELONG_TO]->(:Module)
(:Workflow)-[:CONTAIN]->(:Method)
(:Workflow)-[:CONTAIN]->(:Class)
```

### 3.2 向量数据库模型 (Milvus)

#### Collection 定义

```python
# file_summary_collection
class FileSummarySchema:
    id: str                    # 主键
    name: str                  # 文件名称
    node_id: str               # 图节点ID
    repo: str                  # 仓库名称
    summary: str               # LLM摘要
    embedding: list[float]     # 向量 (768/1024/1536 维度)

# class_summary_collection
class ClassSummarySchema:
    id: str
    name: str
    node_id: str
    repo: str
    summary: str
    embedding: list[float]

# method_summary_collection
class MethodSummarySchema:
    id: str
    name: str
    node_id: str
    repo: str
    summary: str
    embedding: list[float]

# semantic_summary_collection
class SemanticSummarySchema:
    id: str
    name: str
    node_id: str
    type: str                  # Module / Workflow
    repo: str
    summary: str
    embedding: list[float]

# semantic_detail_collection
class SemanticDetailSchema:
    id: str
    name: str
    node_id: str
    type: str                  # Module / Workflow
    repo: str
    detail: str                # LLM详情
    embedding: list[float]

# class_code_collection
class ClassCodeSchema:
    id: str
    name: str
    node_id: str
    repo: str
    path: str
    code: str
    embedding: list[float]

# method_code_collection
class MethodCodeSchema:
    id: str
    name: str
    node_id: str
    repo: str
    path: str
    code: str
    embedding: list[float]
```

### 3.3 流水线状态模型

```python
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any

class PipelineStage(Enum):
    REPO_TRAVERSAL = "repo_traversal"           # 仓库遍历
    CODE_PARSING = "code_parsing"               # 代码分析
    SYMBOL_EXTRACTION = "symbol_extraction"     # 符号提取
    STRUCTURE_GRAPH_BUILD = "structure_graph_build"  # 结构图构建
    DEPENDENCY_ANALYSIS = "dependency_analysis" # 依赖分析
    DEPENDENCY_GRAPH_BUILD = "dependency_graph_build"  # 依赖图构建
    SEMANTIC_ANALYSIS = "semantic_analysis"     # 语义分析
    EMBEDDING_GENERATION = "embedding_generation"  # 向量化
    VECTOR_DB_STORE = "vector_db_store"         # 向量存储
    MODULE_DETECTION = "module_detection"       # 模块检测
    SEMANTIC_GRAPH_BUILD = "semantic_graph_build"  # 语义图构建
    COMPLETED = "completed"                     # 完成
    FAILED = "failed"                           # 失败

class PipelineStatus(Enum):
    PENDING = "pending"         # 等待执行
    RUNNING = "running"         # 执行中
    COMPLETED = "completed"     # 完成
    FAILED = "failed"           # 失败
    PAUSED = "paused"           # 暂停（可恢复）

class StageResult:
    stage: PipelineStage
    status: PipelineStatus
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    message: str
    metadata: Dict[str, Any]    # 阶段特定数据

class PipelineState:
    pipeline_id: str
    repo_path: str
    repo_name: str
    current_stage: PipelineStage
    overall_status: PipelineStatus
    stages: Dict[PipelineStage, StageResult]
    created_at: datetime
    updated_at: datetime
    checkpoint_data: Dict[str, Any]  # 断点续传数据
```

## 四、构建流水线设计

### 4.1 流水线架构

```python
class PipelineOrchestrator:
    """流水线编排器，负责任务调度、状态管理和断点恢复"""

    def __init__(self):
        self.stages: List[PipelineStage] = []
        self.state_manager: PipelineStateManager
        self.event_bus: EventBus

    async def execute(self, repo_path: str, resume_from: Optional[PipelineStage] = None):
        """执行流水线，支持从指定阶段恢复"""

    async def execute_stage(self, stage: PipelineStage, context: PipelineContext):
        """执行单个阶段，带错误处理和日志"""

    async def checkpoint(self, stage: PipelineStage, data: Any):
        """保存断点数据"""

    async def rollback(self, to_stage: PipelineStage):
        """回滚到指定阶段"""
```

### 4.2 阶段详细设计

#### Stage 1: 仓库遍历 (RepoTraversal)
```python
class RepoTraversalStage:
    """遍历仓库文件系统，生成文件列表"""

    async def execute(self, context: PipelineContext) -> TraversalResult:
        # 1. 扫描仓库目录
        # 2. 识别文件类型（代码/文档/配置）
        # 3. 过滤忽略文件（.gitignore）
        # 4. 生成文件列表和目录结构
        # 5. 创建 Repository 和 Directory 节点
```

#### Stage 2: 代码解析 (CodeParsing)
```python
class CodeParsingStage:
    """使用 tree-sitter 解析代码文件"""

    async def execute(self, context: PipelineContext) -> ParsingResult:
        # 1. 根据文件后缀选择解析器
        # 2. 解析代码生成 AST
        # 3. 提取原始符号信息

class TreeSitterParser:
    """Tree-sitter 解析器封装"""

    def __init__(self):
        self.languages: Dict[str, Language] = {}

    def parse_file(self, file_path: str, content: str) -> ASTNode:
        # 解析单个文件

    def get_parser_for_language(self, lang: str) -> Parser:
        # 获取对应语言的解析器
```

#### Stage 3: 符号提取 (SymbolExtraction)
```python
class SymbolExtractor:
    """从 AST 中提取 Class 和 Method 符号"""

    async def extract(self, ast: ASTNode, file_path: str) -> List[Symbol]:
        # 1. 遍历 AST
        # 2. 识别 Class/Struct/Interface 定义
        # 3. 识别 Method/Function 定义
        # 4. 提取位置信息、代码片段、文档字符串
```

#### Stage 4: 结构图构建 (StructureGraphBuild)
```python
class StructureGraphBuilder:
    """构建代码结构图"""

    async def build(self, symbols: List[Symbol]) -> GraphResult:
        # 1. 创建 File 节点
        # 2. 创建 Class 节点，建立 File-[:CONTAIN]->Class 关系
        # 3. 创建 Method 节点，建立 Class-[:CONTAIN]->Method 关系
        # 4. 建立 Directory-[:CONTAIN]->File 关系
```

#### Stage 5: 依赖分析 (DependencyAnalysis)
```python
class DependencyAnalyzer:
    """分析代码间的依赖关系"""

    async def analyze(self, symbols: List[Symbol]) -> DependencyResult:
        # 1. 分析方法调用关系
        # 2. 分析类继承关系
        # 3. 分析接口实现关系
        # 4. 分析文件引用关系

    def analyze_method_calls(self, method: MethodSymbol) -> List[CallRelation]:
        # 分析方法内部的调用关系

    def analyze_inheritance(self, class_symbol: ClassSymbol) -> List[InheritRelation]:
        # 分析类的继承链
```

#### Stage 6: 依赖图构建 (DependencyGraphBuild)
```python
class DependencyGraphBuilder:
    """构建代码依赖图"""

    async def build(self, dependencies: DependencyResult):
        # 1. 创建 Method-[:CALL]->Method 关系
        # 2. 创建 Class-[:INHERIT]->Class 关系
        # 3. 创建 Class-[:IMPLEMENT]->Class 关系
        # 4. 创建 File-[:USE]->File 关系
```

#### Stage 7: 语义分析 (SemanticAnalysis)
```python
class SemanticAnalyzer:
    """使用 LLM 生成代码摘要"""

    async def analyze(self, context: PipelineContext) -> SemanticResult:
        # 1. 基于依赖图拓扑排序，自底向上生成摘要
        # 2. 先为叶子 Method 生成摘要
        # 3. 使用被调用 Method 的摘要生成调用方摘要
        # 4. 使用 Method 摘要生成 Class 摘要
        # 5. 使用 Class/Method 摘要生成 File 摘要

    async def generate_method_summary(
        self,
        method: MethodNode,
        callee_summaries: List[str]
    ) -> str:
        # 生成方法摘要

    async def generate_class_summary(
        self,
        class_node: ClassNode,
        method_summaries: List[str]
    ) -> str:
        # 生成类摘要
```

#### Stage 8: 向量化 (EmbeddingGeneration)
```python
class EmbeddingService:
    """向量化服务"""

    async def generate_embeddings(self, summaries: List[Summary]) -> List[Embedding]:
        # 1. 批量调用 Embedding API
        # 2. 处理限流和重试
        # 3. 返回向量结果
```

#### Stage 9: 向量存储 (VectorDBStore)
```python
class VectorDBStoreStage:
    """存储向量到 Milvus"""

    async def store(self, embeddings: List[Embedding]):
        # 1. 批量插入到对应 Collection
        # 2. 更新图节点中的 embeddingId
```

#### Stage 10: 模块检测 (ModuleDetection)
```python
class ModuleDetector:
    """检测功能模块和业务流程"""

    async def detect(self, context: PipelineContext) -> ModuleResult:
        # 1. 将结构图序列化为 JSON
        # 2. 调用 LLM 识别 Module 和 Workflow
        # 3. 解析 LLM 输出，创建 Module/Workflow 节点

    def build_structure_json(self, graph: StructureGraph) -> dict:
        # 将图结构转换为 JSON 树
```

#### Stage 11: 语义图构建 (SemanticGraphBuild)
```python
class SemanticGraphBuilder:
    """构建语义图，连接代码节点和语义节点"""

    async def build(self, modules: ModuleResult):
        # 1. 创建 Module 节点
        # 2. 创建 Workflow 节点
        # 3. 建立 Workflow-[:BELONG_TO]->Module 关系
        # 4. 建立 File/Class/Method-[:BELONG_TO]->Module 关系
```

### 4.3 断点续传机制

```python
class CheckpointManager:
    """断点管理器"""

    async def save(self, stage: PipelineStage, data: Any):
        """保存阶段断点"""
        # 1. 序列化阶段数据
        # 2. 存储到持久化存储（文件/数据库）
        # 3. 更新流水线状态

    async def load(self, pipeline_id: str, stage: PipelineStage) -> Optional[Any]:
        """加载阶段断点数据"""

    async def clear(self, pipeline_id: str):
        """清除断点数据"""
```

## 五、API 接口设计

### 5.1 REST API

#### 启动初始化
```http
POST /api/v1/initialization/start
Request:
{
    "repo_path": "/path/to/repo",
    "repo_name": "my-project",
    "config": {
        "language_filters": [".py", ".java", ".ts"],
        "exclude_patterns": ["node_modules/**", "*.min.js"],
        "llm_config": {
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096
        },
        "embedding_config": {
            "model": "text-embedding-3-large",
            "dimensions": 3072
        }
    }
}

Response:
{
    "pipeline_id": "uuid",
    "status": "running",
    "current_stage": "repo_traversal",
    "created_at": "2024-01-01T00:00:00Z"
}
```

#### 重新初始化
```http
POST /api/v1/initialization/restart
Request:
{
    "repo_path": "/path/to/repo",
    "repo_name": "my-project",
    "clear_existing": true
}

Response:
{
    "pipeline_id": "uuid",
    "status": "running",
    "previous_data_cleared": true
}
```

#### 从指定阶段恢复
```http
POST /api/v1/initialization/resume
Request:
{
    "pipeline_id": "uuid",
    "resume_from": "semantic_analysis"
}
```

#### 获取构建进度
```http
GET /api/v1/initialization/{pipeline_id}/progress

Response:
{
    "pipeline_id": "uuid",
    "repo_name": "my-project",
    "overall_status": "running",
    "current_stage": "code_parsing",
    "progress_percent": 35,
    "stages": [
        {
            "stage": "repo_traversal",
            "status": "completed",
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2024-01-01T00:01:00Z",
            "message": "Scanned 1250 files",
            "metadata": {
                "total_files": 1250,
                "total_directories": 85
            }
        },
        {
            "stage": "code_parsing",
            "status": "running",
            "start_time": "2024-01-01T00:01:00Z",
            "progress": 45,
            "message": "Parsed 563/1250 files"
        }
    ],
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:05:00Z"
}
```

#### 取消构建
```http
POST /api/v1/initialization/{pipeline_id}/cancel

Response:
{
    "pipeline_id": "uuid",
    "status": "cancelled",
    "cancelled_at": "2024-01-01T00:10:00Z"
}
```

### 5.2 MCP Tools

```python
@mcp.tool()
async def get_project_structure(repo_name: str) -> dict:
    """获取项目目录结构"""
    # 返回 Repository-[:CONTAIN]->Directory/File 的树形结构

@mcp.tool()
async def search_nodes(
    repo_name: str,
    query: str,
    node_types: List[str],  # ["File", "Class", "Method", "Module", "Workflow"]
    top_k: int = 10
) -> List[SearchResult]:
    """根据关键字语义查询节点信息"""
    # 1. 将 query 向量化
    # 2. 在对应 Collection 中向量搜索
    # 3. 返回节点信息

@mcp.tool()
async def get_modules(repo_name: str) -> List[ModuleInfo]:
    """获取项目的 Module 列表"""

@mcp.tool()
async def get_module_workflows(
    repo_name: str,
    module_id: str
) -> List[WorkflowInfo]:
    """获取 Module 对应的 Workflow 列表"""

@mcp.tool()
async def get_node_by_id(node_id: str) -> NodeInfo:
    """根据节点 ID 获取节点信息"""
    # 返回节点的完整信息，包括关系

@mcp.tool()
async def get_node_dependencies(
    node_id: str,
    depth: int = 1
) -> DependencyGraph:
    """获取节点的依赖关系图"""

@mcp.tool()
async def get_file_content(file_id: str) -> FileContent:
    """获取文件内容"""

@mcp.tool()
async def search_code(
    repo_name: str,
    query: str,
    top_k: int = 10
) -> List[CodeSearchResult]:
    """语义搜索代码"""
    # 在 class_code_collection 和 method_code_collection 中搜索
```

## 六、关键算法设计

### 6.1 摘要生成顺序算法

```python
async def generate_summaries_in_order(graph: DependencyGraph):
    """
    按照依赖关系自底向上生成摘要
    确保被调用的 Method 优先生成摘要
    """
    # 1. 对 Method 进行拓扑排序
    method_order = topological_sort_methods(graph)

    for method in method_order:
        # 获取被调用方法的摘要
        callee_summaries = [
            callee.summary for callee in method.calls
            if callee.summary
        ]

        # 生成当前方法摘要
        method.summary = await llm.generate_method_summary(
            method=method,
            callee_summaries=callee_summaries
        )

    # 2. 为 Class 生成摘要
    for class_node in graph.classes:
        method_summaries = [
            m.summary for m in class_node.methods
            if m.summary
        ]

        class_node.summary = await llm.generate_class_summary(
            class_node=class_node,
            method_summaries=method_summaries
        )

    # 3. 为 File 生成摘要
    for file_node in graph.files:
        summaries = []
        for class_node in file_node.classes:
            if class_node.summary:
                summaries.append(f"Class {class_node.name}: {class_node.summary}")
        for method in file_node.methods:
            if method.summary:
                summaries.append(f"Method {method.name}: {method.summary}")

        file_node.summary = await llm.generate_file_summary(
            file=file_node,
            component_summaries=summaries
        )
```

### 6.2 批量向量化策略

```python
class BatchingStrategy:
    """批量向量化策略，优化 API 调用"""

    def __init__(self, batch_size: int = 100, max_retries: int = 3):
        self.batch_size = batch_size
        self.max_retries = max_retries

    async def embed_with_retry(self, texts: List[str]) -> List[Embedding]:
        results = []

        for batch in chunks(texts, self.batch_size):
            for attempt in range(self.max_retries):
                try:
                    embeddings = await embedding_client.embed(batch)
                    results.extend(embeddings)
                    break
                except RateLimitError:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        raise

        return results
```

## 七、错误处理与监控

### 7.1 错误分类与处理

```python
class PipelineError(Exception):
    """流水线错误基类"""
    pass

class StageError(PipelineError):
    """阶段执行错误"""
    def __init__(self, stage: PipelineStage, message: str, recoverable: bool = False):
        self.stage = stage
        self.recoverable = recoverable
        super().__init__(message)

class StorageError(PipelineError):
    """存储错误"""
    pass

class LLMError(PipelineError):
    """LLM 调用错误"""
    pass
```

### 7.2 日志与监控

```python
class PipelineLogger:
    """流水线日志记录"""

    def log_stage_start(self, stage: PipelineStage):
        pass

    def log_stage_progress(self, stage: PipelineStage, progress: float, message: str):
        pass

    def log_stage_complete(self, stage: PipelineStage, result: Any):
        pass

    def log_stage_error(self, stage: PipelineStage, error: Exception):
        pass

    def log_checkpoint_saved(self, stage: PipelineStage):
        pass
```

## 八、验证计划

### 8.1 单元测试
```python
# 测试覆盖以下模块
- test_parser.py          # 代码解析器测试
- test_symbol_extractor.py # 符号提取测试
- test_dependency_analyzer.py # 依赖分析测试
- test_graph_builder.py   # 图构建测试
- test_semantic_analyzer.py # 语义分析测试
- test_pipeline.py        # 流水线测试
```

### 8.2 集成测试
```python
# 端到端测试场景
- test_full_pipeline.py   # 完整流水线测试
- test_resume_pipeline.py # 断点恢复测试
- test_api_endpoints.py   # API 接口测试
- test_mcp_tools.py       # MCP 工具测试
```

### 9.3 性能基准
- 支持代码仓库规模: 10000+ 文件
- 流水线完成时间: < 30 分钟（中等规模仓库）
- 向量搜索响应时间: < 100ms
- API 响应时间: < 200ms

## 十、关键设计决策

1. **断点续传存储**: 使用本地 JSON 文件存储断点数据，便于调试和快速恢复
2. **摘要生成策略**: 自底向上、依赖感知的批量生成，减少 LLM 调用次数
3. **向量存储分离**: 不同类型数据存储到不同 Collection，优化检索性能
4. **LLM 容错**: 实现指数退避重试，单个文件失败不影响整体流程
5. **事件驱动**: 使用事件总线解耦流水线各阶段，便于扩展和监控
