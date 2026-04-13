# Knowledge Base Service API 文档

代码知识底座管理服务 API 文档，提供代码仓库解析、知识图谱构建和语义搜索能力。

## 目录

- [概述](#概述)
- [REST API](#rest-api)
  - [初始化管理](#初始化管理)
  - [进度查询](#进度查询)
  - [重置管理](#重置管理)
- [MCP 工具](#mcp-工具)
  - [项目结构查询](#项目结构查询)
  - [节点搜索](#节点搜索)
  - [模块管理](#模块管理)
  - [依赖关系](#依赖关系)
  - [流程图下载](#流程图下载)

---

## 概述

### 基础信息

| 项目 | 说明 |
|------|------|
| 服务名称 | Knowledge Base Service (代码知识底座管理服务) |
| 框架 | FastAPI |
| 数据格式 | JSON |
| 字符编码 | UTF-8 |

### 技术栈

- **Web 框架**: FastAPI
- **图数据库**: Neo4j (存储代码结构关系)
- **向量数据库**: Milvus (语义搜索)
- **代码解析**: Tree-sitter
- **LLM 集成**: LangChain

### 接口类型

1. **REST API** - HTTP 接口，用于流水线控制和管理
2. **MCP Server** - Model Context Protocol 工具，供 AI Agent 调用

---

## REST API

### 基础路径

```
/api/v1
```

### 初始化管理

#### 1. 启动初始化

启动代码知识底座构建流水线。

```http
POST /initialization/start
```

**请求参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库唯一标识 |
| repo_path | string | 是 | 仓库本地路径 |
| repo_name | string | 是 | 仓库名称 |
| config | object | 否 | 配置选项 |

**请求示例**:

```json
{
  "repo_id": "my-project-123",
  "repo_path": "./repos/my-project",
  "repo_name": "my-project",
  "config": {
    "batch_size": 100,
    "max_retries": 3
  }
}
```

**响应参数**:

| 字段 | 类型 | 说明 |
|------|------|------|
| pipeline_id | string | 流水线 ID |
| repo_id | string | 仓库 ID |
| status | string | 状态: pending, running, completed, failed |
| current_stage | string | 当前执行阶段 |
| created_at | string | 创建时间 (ISO 8601) |

**响应示例**:

```json
{
  "pipeline_id": "pipe_abc123",
  "repo_id": "my-project-123",
  "status": "running",
  "current_stage": "structure_graph_build",
  "created_at": "2024-01-15T08:30:00Z"
}
```

---

#### 2. 恢复初始化

从已有的流水线上下文恢复执行。

```http
POST /initialization/resume
```

**请求参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库 ID |

**请求示例**:

```json
{
  "repo_id": "my-project-123"
}
```

**响应参数**: 同 [启动初始化](#1-启动初始化)

---

#### 3. 获取初始化状态

查询仓库的初始化状态。

```http
GET /initialization/{repo_id}/status
```

**路径参数**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |

**响应参数**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |
| status | string | 状态: NotInitialized, Pending, Running, Completed, Failed |
| repo_name | string | 仓库名称 |
| repo_path | string | 仓库路径 |
| message | string | 状态描述信息 |

**状态说明**:

| 状态 | 说明 |
|------|------|
| NotInitialized | 未进行初始化 |
| Pending | 挂起/等待恢复 |
| Running | 初始化进行中 |
| Completed | 初始化成功 |
| Failed | 初始化失败 |

**响应示例**:

```json
{
  "repo_id": "my-project-123",
  "status": "Completed",
  "repo_name": "my-project",
  "repo_path": "./repos/my-project",
  "message": "Initialization completed successfully"
}
```

---

### 进度查询

#### 4. 获取流水线进度

获取指定仓库的流水线构建进度详情。

```http
GET /progress/{repo_id}/progress
```

**路径参数**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |

**响应参数**:

| 字段 | 类型 | 说明 |
|------|------|------|
| pipeline_id | string | 流水线 ID |
| repo_name | string | 仓库名称 |
| overall_status | string | 整体状态 |
| current_stage | string | 当前阶段 |
| progress | float | 进度百分比 (0-100) |
| pipeline_msg | string | 流水线运行信息 |
| stage_msg | string | 阶段执行信息 |
| created_at | string | 创建时间 |
| updated_at | string | 更新时间 |

**响应示例**:

```json
{
  "pipeline_id": "pipe_abc123",
  "repo_name": "my-project",
  "overall_status": "running",
  "current_stage": "structure_graph_build",
  "progress": 45.5,
  "pipeline_msg": "Processing repository files...",
  "stage_msg": "Parsing Python files: 150/300",
  "created_at": "2024-01-15T08:30:00Z",
  "updated_at": "2024-01-15T08:35:20Z"
}
```

---

### 重置管理

#### 5. 重置初始化

重置仓库的初始化状态，清除所有相关数据。

```http
POST /reset/{repo_id}/reset
```

**路径参数**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |

**执行操作**:

1. 删除图数据库(Neo4j)中对应仓库的所有节点数据
2. 删除向量数据库(Milvus)中对应仓库的所有数据
3. 在 `repo_initialization.csv` 文件中删除对应仓库记录
4. 清除仓库 log 目录下的上下文 JSON 文件，执行日志移入 history 文件夹

**响应参数**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |
| success | boolean | 是否全部成功 |
| message | string | 操作结果描述 |
| details | object | 详细操作结果 |

**details 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| graph_db_deleted | boolean | 图数据库删除状态 |
| graph_db_deleted_count | int | 删除的节点数量 |
| vector_db_deleted | boolean | 向量数据库删除状态 |
| vector_db_deleted_stats | object | 删除统计信息 |
| csv_record_deleted | boolean | CSV 记录删除状态 |
| logs_reset | boolean | 日志重置状态 |

**响应示例**:

```json
{
  "repo_id": "my-project-123",
  "success": true,
  "message": "仓库 my-project-123 初始化状态已重置",
  "details": {
    "graph_db_deleted": true,
    "graph_db_deleted_count": 1250,
    "vector_db_deleted": true,
    "vector_db_deleted_stats": {
      "file_summary_collection": 100,
      "class_summary_collection": 50
    },
    "csv_record_deleted": true,
    "logs_reset": true
  }
}
```

---

## MCP 工具

MCP (Model Context Protocol) 工具供 AI Agent 调用，提供知识库查询能力。

### 工具列表

| 工具名称 | 功能描述 |
|----------|----------|
| get_project_structure | 获取项目目录结构 |
| search_code_nodes | 根据关键字语义查询代码节点 (FILE, CLASS, METHOD) |
| search_semantic_nodes | 根据关键字语义查询语义节点 (MODULE, WORKFLOW) |
| get_modules | 获取项目的 Module 列表 |
| get_module_workflows | 获取 Module 对应的 Workflow 列表 |
| get_node_dependencies | 获取节点的依赖关系图 |
| batch_download_flowcharts | 批量下载方法流程图图片 |

---

### 项目结构查询

#### get_project_structure

获取项目的目录结构（文件和文件夹）。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |

**返回值**: JSON 字符串

```json
{
  "repository": "my-project-123",
  "items": [
    {"id": "dir_my-project_src", "path": "src/", "type": "Directory"},
    {"id": "file_my-project_src/main.py", "path": "src/main.py", "type": "File", "summary": "主入口文件，包含应用程序启动逻辑"},
    {"id": "dir_my-project_src/utils", "path": "src/utils/", "type": "Directory"}
  ]
}
```

---

### 节点搜索

#### search_code_nodes

根据关键字语义搜索代码节点 (FILE, CLASS, METHOD)。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| query | string | 是 | 查询关键字 |
| node_types | array | 否 | 节点类型列表，默认 ["File", "Class", "Method"] |
| top_k | int | 否 | 返回结果数量，默认 10 |

**支持的节点类型**:

- `File` - 文件节点
- `Class` - 类节点
- `Method` - 方法节点

**返回值**: JSON 字符串

```json
{
  "query": "用户认证",
  "results": [
    {
      "node_id": "class_auth_001",
      "name": "AuthService",
      "type": "Class",
      "distance": 0.95,
      "summary": "处理用户认证逻辑的服务类",
      "details": {
        "name": "AuthService",
        "filePath": "src/auth/service.py",
        "summary": "处理用户认证逻辑的服务类"
      }
    }
  ]
}
```

---

#### search_semantic_nodes

根据关键字语义搜索语义节点 (MODULE, WORKFLOW)。

**说明**: 只使用 summary 进行语义匹配，但会同时返回 detail 字段。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| query | string | 是 | 查询关键字 |
| node_types | array | 否 | 节点类型列表，默认 ["Module", "Workflow"] |
| top_k | int | 否 | 返回结果数量，默认 10 |

**支持的节点类型**:

- `Module` - 功能模块节点
- `Workflow` - 工作流节点

**返回值**: JSON 字符串

```json
{
  "query": "用户认证",
  "results": [
    {
      "node_id": "module_auth_001",
      "name": "Authentication Module",
      "type": "Module",
      "distance": 0.92,
      "summary": "处理用户登录、注册、Token验证等认证功能",
      "detail": "本模块包含用户注册流程、登录验证流程、Token生成与验证、密码重置等功能。主要组件包括：UserService处理用户相关操作，AuthService处理认证逻辑，TokenManager管理JWT Token。"
    }
  ]
}
```

---

### 模块管理

#### get_modules

获取项目中所有检测到的功能模块列表。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |

**返回值**: JSON 字符串

```json
{
  "repo_id": "my-project-123",
  "modules": [
    {
      "id": "module_my-project-123_auth",
      "name": "Authentication",
      "description": "用户认证模块",
      "summary": "处理用户登录、注册、Token 验证等功能"
    }
  ]
}
```

---

#### get_module_workflows

获取指定模块下的所有工作流列表。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| module_id | string | 是 | 模块 ID |

**返回值**: JSON 字符串

```json
{
  "module_id": "module_my-project_auth",
  "workflows": [
    {
      "id": "workflow_login",
      "name": "User Login Flow",
      "description": "用户登录流程",
      "summary": "用户输入凭证 -> 验证 -> 生成 Token"
    }
  ]
}
```

---

### 依赖关系

#### get_node_dependencies

获取节点的依赖关系图，支持指定深度。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| node_id | string | 是 | 节点 ID |
| depth | int | 否 | 依赖深度，默认 1，最大建议 3 |

**返回值**: JSON 字符串

```json
{
  "node_id": "class_auth_001",
  "depth": 2,
  "dependencies": [
    {
      "source": {"id": "class_auth_001", "labels": ["Class"]},
      "target": {"id": "class_user_001", "labels": ["Class"]},
      "relationships": ["DEPENDS_ON"],
      "distance": 1
    }
  ]
}
```

---

### 流程图下载

#### batch_download_flowcharts

根据 method 节点 ID 列表批量下载流程图图片。每个流程图对应一个 method 节点的控制流程图。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| method_ids | array[string] | 是 | Method 节点 ID 列表 |

**返回值**: JSON 字符串

```json
{
  "success": true,
  "total": 2,
  "success_count": 1,
  "failed_count": 1,
  "images": [
    {
      "method_id": "method_repo_file.cpp_func1",
      "method_name": "func1",
      "success": true,
      "image_id": "uuid-string",
      "image_data": "base64-encoded-image-data",
      "image_format": "png"
    },
    {
      "method_id": "method_repo_file.cpp_func2",
      "success": false,
      "error": "No flowchart image available"
    }
  ]
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| success | boolean | 是否有至少一个图片下载成功 |
| total | int | 请求的 method ID 总数 |
| success_count | int | 成功下载的图片数量 |
| failed_count | int | 失败的下载数量 |
| images | array | 每个 method 的下载结果 |

**images 数组元素说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| method_id | string | Method 节点 ID |
| method_name | string | 方法名称（成功时返回） |
| success | boolean | 是否下载成功 |
| image_id | string | 图片唯一标识（成功时返回） |
| image_data | string | Base64 编码的图片数据（成功时返回） |
| image_format | string | 图片格式，固定为 "png"（成功时返回） |
| error | string | 错误信息（失败时返回） |

---

## 流水线阶段说明

知识底座构建流水线包含以下阶段（按执行顺序）：

| 阶段 | 说明 | 权重 |
|------|------|------|
| structure_graph_build | 扫描仓库，使用 Tree-sitter 解析代码，构建结构图谱 | 3.0 |
| dependency_graph_build | 构建代码依赖关系图谱 | 2.0 |
| semantic_analysis | 使用 LLM 生成代码摘要 | 2.0 |
| flowchart_generation | 为 C/CPP 方法生成控制流程图 | 1.0 |
| module_detection | 检测功能模块，构建语义图谱 | 1.5 |
| vector_db_store | 提取内容，生成向量嵌入并存储 | 1.5 |

---

## 错误处理

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 404 | 资源不存在 (如流水线未找到) |
| 500 | 服务器内部错误 |

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

---

## 数据模型

### PipelineStage 枚举

```python
enum PipelineStage {
  STRUCTURE_GRAPH_BUILD = "structure_graph_build"
  DEPENDENCY_GRAPH_BUILD = "dependency_graph_build"
  SEMANTIC_ANALYSIS = "semantic_analysis"
  FLOWCHART_GENERATION = "flowchart_generation"
  MODULE_DETECTION = "module_detection"
  VECTOR_DB_STORE = "vector_db_store"
  COMPLETED = "completed"
  FAILED = "failed"
}
```

### PipelineStatus 枚举

```python
enum PipelineStatus {
  PENDING = "pending"
  RUNNING = "running"
  COMPLETED = "completed"
  FAILED = "failed"
  PAUSED = "paused"
}
```

---

## 配置说明

环境变量配置（.env 文件）：

```bash
# Neo4j 图数据库
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Milvus 向量数据库
MILVUS_HOST=localhost
MILVUS_PORT=19530

# LLM 配置
LLM_PROVIDER=qwen          # 可选: qwen, openai, anthropic
DASHSCOPE_API_KEY=your-key

# 流水线配置
BATCH_SIZE=100
MAX_RETRIES=3

# 流程图生成服务配置
FLOWCHART_SERVICE_URL=http://localhost:18765
FLOWCHART_SERVICE_TIMEOUT=30
FLOWCHART_IMAGE_DIR=./data
```
