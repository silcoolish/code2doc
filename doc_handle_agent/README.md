# 文档处理Agent服务 (doc_handle_agent)

基于LangGraph的智能文档生成Agent服务，根据代码知识底座和模板文档自动生成设计说明文档。

## 功能特性

- **模板驱动生成**: 支持docx格式模板，通过标记定义内容生成规则
- **智能内容生成**: 使用LLM根据代码知识库自动生成技术文档内容
- **MCP协议集成**: 通过MCP调用知识底座服务获取代码信息
- **异步流程**: 支持并发生成多个文档，实时查询进度
- **可扩展设计**: 支持自定义工具和LLM模型

## 系统架构

```
┌────────────────────────────────────────────────────────────────┐
│                   文档处理Agent服务                             │
│                                                                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │  FastAPI     │◄───│  LangGraph   │◄───│ Document Engine  │ │
│  │  Web API     │    │   Agent      │    │                  │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                   │            │
│  ┌──────────────┐    ┌──────────────┐            │            │
│  │ Template     │    │ Docx         │◄───────────┘            │
│  │ Parser       │    │ Handler      │                         │
│  └──────────────┘    └──────────────┘                         │
│                                                                │
└────────────────────────────────┬───────────────────────────────┘
                                 │ MCP Protocol
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│                   知识底座服务 (knowledge_base_service)         │
│                                                                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │  MCP Server  │    │  Neo4j       │    │  Milvus          │ │
│  │  (8 tools)   │    │  Graph DB    │    │  Vector DB       │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 环境准备

```bash
# 使用conda环境（与knowledge_base_service一致）
conda activate code2Doc

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑.env文件，配置API密钥和路径
```

### 3. 启动服务

```bash
uvicorn app.main:app --reload --port 8001
```

服务启动后访问:
- API文档: http://localhost:8001/docs
- 健康检查: http://localhost:8001/health

## API接口

### 启动文档生成

```bash
POST /api/v1/documents/generate
Content-Type: application/json

{
  "repo_id": "my-project-001",
  "template_path": "templates/design_doc_template.docx",
  "output_filename": "my_project_design.docx"
}
```

**响应**:
```json
{
  "flow_id": "doc_my-project-001_20250404_143052",
  "status": "parsing",
  "repo_id": "my-project-001",
  "template_path": "templates/design_doc_template.docx",
  "output_path": "output/my_project_design.docx",
  "created_at": "2025-04-04T14:30:52"
}
```

### 获取生成进度

```bash
GET /api/v1/documents/{flow_id}/progress
```

**响应**:
```json
{
  "flow_id": "doc_my-project-001_20250404_143052",
  "status": "generating",
  "progress": 45.5,
  "current_step": 5,
  "total_steps": 11,
  "message": "正在生成第5个内容块: 系统架构设计...",
  "output_path": "output/my_project_design.docx"
}
```

### 预览模板

```bash
POST /api/v1/documents/preview-template
Content-Type: application/json

{
  "template_path": "templates/design_doc_template.docx"
}
```

## 模板格式

模板使用 `{{...}}` 标记定义内容块:

### 文本内容块

```json
{{"type":"text", "prompt":"系统的功能概述"}}
```

### 标题内容块

```json
{{"type":"headline", "prompt":"系统的模块功能", "list":"true", "min_length":"5", "max_length":"20"}}
```

### 完整示例

```
# 系统设计文档

## 1. 系统概述
{{"type":"text", "prompt":"系统的整体功能概述，包括主要业务目标"}}

## 2. 系统架构
{{"type":"text", "prompt":"系统的技术架构和部署架构说明"}}

## 3. 功能模块
{{"type":"headline", "prompt":"系统的主要功能模块", "list":"true", "min_length":"3", "max_length":"10"}}

## 4. 核心流程
{{"type":"text", "prompt":"系统的核心业务处理流程"}}
```

## 项目结构

```
doc_handle_agent/
├── app/
│   ├── api/                 # Web API层
│   │   ├── models/          # Pydantic模型
│   │   └── routes/          # API路由
│   ├── core/                # 核心业务逻辑
│   │   ├── template_parser.py   # 模板解析器
│   │   ├── generator.py         # LangGraph工作流
│   │   ├── document_engine.py   # 文档生成引擎
│   │   ├── content_generator.py # 内容生成器
│   │   └── state.py             # 状态定义
│   ├── infrastructure/      # 基础设施层
│   │   ├── mcp_client.py    # MCP客户端
│   │   ├── llm_client.py    # LLM客户端
│   │   └── docx_handler.py  # docx处理器
│   ├── utils/               # 工具函数
│   ├── config.py            # 配置管理
│   └── main.py              # 应用入口
├── tests/                   # 测试文件
├── templates/               # 模板存储目录
├── output/                  # 生成文档输出目录
├── requirements.txt
└── .env.example
```

## 开发指南

### 添加新的MCP工具

在 `app/infrastructure/mcp_client.py` 中添加工具方法:

```python
async def custom_tool(self, param: str) -> Dict[str, Any]:
    result = await self.call_tool("custom_tool", {"param": param})
    return json.loads(result)
```

### 更换LLM模型

在 `app/infrastructure/llm_client.py` 中实现新的客户端:

```python
class OpenAIClient(BaseLLMClient):
    async def generate(self, prompt, system_prompt=None, tools=None):
        # 实现生成逻辑
        pass
```

## 测试

```bash
# 运行所有测试
pytest

# 运行单元测试
pytest tests/unit/

# 运行集成测试
pytest tests/integration/
```

## 依赖

- Python 3.11+
- FastAPI 0.109+
- LangGraph 0.0.50+
- MCP 0.5+
- python-docx 1.1+

## 与知识底座服务的协作

文档处理Agent服务依赖知识底座服务提供的MCP接口:

1. **get_project_structure** - 获取项目目录结构
2. **search_nodes** - 语义查询代码节点
3. **get_modules** - 获取模块列表
4. **get_module_workflows** - 获取工作流列表
5. **get_node_by_id** - 获取节点详情
6. **get_node_dependencies** - 获取依赖关系
7. **get_file_content** - 获取文件内容
8. **search_code** - 语义搜索代码

启动本服务前，请确保知识底座服务已启动并完成了代码仓库的初始化。

## License

MIT
