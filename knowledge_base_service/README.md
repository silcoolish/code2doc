# Knowledge Base Service

代码知识底座管理服务 - 用于解析代码仓库，构建代码知识图谱，并提供语义检索能力。

## 功能特性

- **代码解析**: 使用 Tree-sitter 解析多种编程语言
- **三层图结构**: 结构图 + 依赖图 + 语义图
- **语义分析**: 使用 LLM 生成代码摘要
- **向量检索**: 基于 Milvus 的语义搜索
- **流水线架构**: 支持断点续传和阶段恢复
- **MCP 支持**: 提供 MCP 工具供文档生成 Agent 使用

## 技术栈

- **Python 3.11**
- **FastAPI**: Web 框架
- **Neo4j**: 图数据库
- **Milvus**: 向量数据库
- **Tree-sitter**: 代码解析
- **Langchain**: LLM 和嵌入模型

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，并配置数据库连接和 API 密钥：

```bash
cp .env.example .env
```

### 3. 启动服务

```bash
cd knowledge_base_service
uvicorn app.main:app --reload
```

服务将在 http://localhost:8000 启动。

## API 接口

### 初始化相关

- `POST /api/v1/initialization/start` - 启动构建流水线
- `POST /api/v1/initialization/resume` - 从指定阶段恢复
- `GET /api/v1/initialization/{repo_id}/status` - 获取仓库初始化状态
- `GET /api/v1/initialization/{repo_id}/progress` - 获取仓库初始化构建进度

### 请求示例

```bash
# 启动初始化
curl -X POST http://localhost:8000/api/v1/initialization/start \
  -H "Content-Type: application/json" \
  -d '{
    "repo_id": "repo_id",
    "repo_path": "/path/to/your/repo",
    "repo_name": "my-project"
  }'

# 获取进度
curl http://localhost:8000/api/v1/initialization/{repo_id}/progress
```

## MCP 工具

服务提供以下 MCP 工具供文档生成 Agent 使用：

1. **get_project_structure** - 获取项目目录结构
2. **search_nodes** - 语义搜索节点
3. **get_modules** - 获取模块列表
4. **get_module_workflows** - 获取模块工作流
5. **get_node_by_id** - 根据ID获取节点
6. **get_node_dependencies** - 获取节点依赖
7. **get_file_content** - 获取文件内容
8. **search_code** - 语义搜索代码

## 流水线阶段

1. **repo_traversal** - 仓库遍历
2. **code_parsing** - 代码解析
3. **symbol_extraction** - 符号提取
4. **structure_graph_build** - 结构图构建
5. **dependency_analysis** - 依赖分析
6. **dependency_graph_build** - 依赖图构建
7. **semantic_analysis** - 语义分析
8. **embedding_generation** - 向量化
9. **vector_db_store** - 向量存储
10. **module_detection** - 模块检测（包含语义图构建）

## 项目结构

```
knowledge_base_service/
├── app/
│   ├── api/              # REST API 路由
│   ├── core/             # 流水线核心
│   ├── domain/           # 领域层
│   │   ├── models/       # 数据模型
│   │   ├── parser/       # 代码解析器
│   │   ├── analyzer/     # 分析器
│   │   └── llm/          # LLM 客户端
│   ├── infrastructure/   # 基础设施
│   │   └── db/           # 数据库客户端
│   ├── mcp/              # MCP 服务器
│   ├── utils/            # 工具函数
│   ├── config.py         # 配置管理
│   └── main.py           # 应用入口
├── tests/                # 测试
├── requirements.txt      # 依赖
└── README.md            # 本文档
```

## 测试

```bash
# 运行测试
pytest

# 运行覆盖率测试
pytest --cov=app --cov-report=html
```

## 许可证

MIT
