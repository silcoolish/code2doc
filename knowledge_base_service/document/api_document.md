# Knowledge Base Service API 文档

代码知识底座管理服务 API 文档，提供代码仓库解析、知识图谱构建和语义搜索能力。

## 目录

- [概述](#概述)
  - [静态文件服务](#静态文件服务)
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
3. **静态文件服务** - 提供流程图图片等静态资源访问

### 静态文件服务

服务通过 `/static` 路径提供对 `app/data` 目录的静态文件访问。

**基础路径**:

```
/static/{repo_id}/image/{filename}
```

**示例**:

```
http://localhost:8000/static/repo_b087a727a064488f9078f5c0bbc00624/image/Libraries_STM32F10x_StdPeriph_Driver_src_stm32f10x_tim_c_TIM_DeInit__L1.svg
```

**说明**:
- 流程图生成后，Method 节点的 `image` 属性将存储完整的可访问 URL
- 支持直接通过 URL 在 Markdown 中展示图片: `![流程图](http://localhost:8000/static/...)`
- 支持 SVG 和 PNG 两种格式

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
    "vector_db_deleted_stats": 150,
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
| search_nodes | 统一搜索节点（语义搜索 + 名称搜索，支持代码节点和语义节点） |
| get_related_nodes | 批量获取与指定节点具有特定关系的所有节点 |
| get_node_dependencies | 批量获取节点的依赖关系图 |
| get_all_nodes | 获取仓库里的所有指定类型节点（File/Class/Method/Module/Workflow/Directory） |
| batch_get_node_details | 批量根据节点ID获取节点详情（代码、摘要、文件路径等） |
| batch_get_image_urls | 根据节点ID列表批量获取节点对应图片的 URL |


---

### 仓库统计查询

#### get_repo_stats

获取仓库的统计信息，包括规模判定、文件数量、代码行数、语言分布等。用于在制定文档生成策略、评估仓库复杂度、判断是否需要分模块处理时快速了解仓库规模。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |

**返回值**: JSON 字符串

```json
{
  "repo_id": "my-project-123",
  "name": "my-project",
  "path": "/path/to/repo",
  "scale": "medium",
  "statistics": {
    "total_files": 1200,
    "total_code_files": 800,
    "total_lines": 45000,
    "total_size": 5242880,
    "directories": 150,
    "classes": 120,
    "methods": 450
  },
  "languages": ["python", "java"],
  "language_distribution": {
    "python": 500,
    "java": 300
  },
  "derived_metrics": {
    "code_file_ratio": 0.67,
    "avg_file_size": 4372,
    "avg_lines_per_code_file": 56
  }
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |
| name | string | 仓库名称 |
| path | string | 仓库根目录路径 |
| scale | string | 规模等级：`small`(小)、`medium`(中)、`large`(大) |
| statistics | object | 核心统计指标 |
| statistics.total_files | int | 所有文件总数 |
| statistics.total_code_files | int | 代码文件数 |
| statistics.total_lines | int | 代码文件总行数 |
| statistics.total_size | int | 所有文件总大小（字节） |
| statistics.directories | int | 目录总数 |
| statistics.classes | int | 类/结构体总数 |
| statistics.methods | int | 方法/函数总数 |
| languages | array[string] | 检测到的编程语言列表（去重排序） |
| language_distribution | object | 各语言对应的代码文件数量 |
| derived_metrics | object | 派生指标 |
| derived_metrics.code_file_ratio | float | 代码文件占比（0-1） |
| derived_metrics.avg_file_size | int | 平均文件大小（字节） |
| derived_metrics.avg_lines_per_code_file | int | 平均每代码文件行数 |

**scale 判定规则**：

| 等级 | 条件 |
|------|------|
| small | 代码文件 < 100 且 总行数 < 1万 |
| medium | 代码文件 100-1000 或 总行数 1万-10万 |
| large | 代码文件 > 1000 或 总行数 > 10万 |

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

#### search_nodes

统一搜索代码节点入口，支持两种搜索模式：
- `semantic`（语义搜索）：基于向量相似度，按功能描述查找代码。适用于想找"做某件事"的代码但不知道确切名称的场景。
- `name`（名称搜索）：基于图数据库名称匹配，按确切名称查找代码。适用于已明确知道类名/方法名时的快速定位。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| queries | array | 是 | 查询参数列表 |

**queries 数组元素说明**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 搜索关键字 |
| search_mode | string | 否 | 搜索模式，`"semantic"` 或 `"name"`，默认 `"semantic"` |
| node_types | array | 否 | 节点类型列表，默认 `["File", "Class", "Method"]` |
| top_k | int | 否 | 返回结果数量，默认 10 |
| fuzzy | boolean | 否 | 仅 `search_mode="name"` 时有效，是否模糊匹配，默认 `true` |
| returns | array | 否 | 指定返回字段列表，如 `["node_id", "name", "summary"]`，减少 token 消耗 |

**支持的节点类型**:

- `File` - 文件节点
- `Class` - 类节点
- `Method` - 方法节点
- `Module` - 功能模块节点
- `Workflow` - 工作流节点

**请求示例**:

```json
{
  "repo_id": "my-project-123",
  "queries": [
    {"query": "用户认证", "search_mode": "semantic", "node_types": ["Class", "Method"], "top_k": 5},
    {"query": "订单模块", "search_mode": "semantic", "node_types": ["Module"], "top_k": 3},
    {"query": "OrderService", "search_mode": "name", "node_types": ["Class"], "fuzzy": false, "top_k": 5, "returns": ["node_id", "name", "summary"]},
    {"query": "create", "search_mode": "name", "node_types": ["Method"], "fuzzy": true, "top_k": 10}
  ]
}
```

**返回值**: JSON 字符串

```json
{
  "repo_id": "my-project-123",
  "results": [
    {
      "query": "用户认证",
      "search_mode": "semantic",
      "node_types": ["Class", "Method"],
      "results": [
        {
          "node_id": "class_auth_001",
          "name": "AuthService",
          "node_type": "Class",
          "distance": 0.95,
          "summary": "处理用户认证逻辑的服务类",
          "file_path": "src/auth/service.py"
        }
      ]
    },
    {
      "query": "订单模块",
      "search_mode": "semantic",
      "node_types": ["Module"],
      "results": [
        {
          "node_id": "module_order_001",
          "name": "Order Module",
          "node_type": "Module",
          "distance": 0.92,
          "summary": "订单核心业务模块",
          "details": "本模块处理订单创建、查询、取消等全流程业务。"
        }
      ]
    },
    {
      "query": "OrderService",
      "search_mode": "name",
      "node_types": ["Class"],
      "results": [
        {
          "node_id": "class_order_001",
          "name": "OrderService",
          "node_type": "Class",
          "file_path": "src/order/service.py",
          "summary": "订单核心业务服务类，处理订单创建、查询、取消等操作"
        }
      ]
    }
  ]
}
```

**说明**:
- 语义搜索基于 Milvus 向量数据库，所有节点类型统一存储在 `code_vectors` collection 中，通过 `type` 字段区分
- 名称搜索基于 Neo4j 图数据库，使用 `CONTAINS`（模糊）或 `=`（精确）匹配节点 `name` 属性
- 同名节点可能返回多条结果，请结合 `file_path` 字段进行甄别
- 使用 `returns` 参数可以只返回需要的字段，显著减少 token 消耗
- Module/Workflow 搜索会额外返回 `details` 字段，包含模块/工作流的详细设计信息（从图数据库实时查询）

---

### 关联节点查询

#### get_related_nodes

批量获取与指定节点具有特定关系的所有节点。这是一个通用关系查询工具，可替代各种专用的"获取子节点"类操作。

**典型使用场景**：
- 获取模块下的所有工作流：`node_id=模块ID, rel_type="BELONG_TO", direction="in"`
- 获取文件包含的所有类/方法：`node_id=文件ID, rel_type="CONTAIN", direction="out"`
- 获取类包含的所有方法：`node_id=类ID, rel_type="CONTAIN", direction="out"`
- 获取方法调用的所有方法：`node_id=方法ID, rel_type="CALL", direction="out"`
- 获取引用某个文件的所有文件：`node_id=文件ID, rel_type="USE", direction="in"`

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| queries | array | 是 | 查询参数列表 |

**queries 数组元素说明**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| node_id | string | 是 | 节点 ID |
| rel_type | string | 是 | 关系类型枚举值 |
| direction | string | 否 | 关系方向，默认 `"out"` |
| returns | array[string] | 否 | 指定返回字段列表，减少 token 消耗 |

**rel_type 枚举值**：

| 枚举值 | 说明 |
|--------|------|
| `BELONG_TO` | 属于关系（如 Workflow 属于 Module） |
| `CONTAIN` | 包含关系（如 File 包含 Class/Method） |
| `CALL` | 调用关系（Method 调用 Method） |
| `USE` | 使用关系（File 使用 File） |

**direction 枚举值**：

| 枚举值 | 说明 |
|--------|------|
| `out` | 获取该节点指向的节点（ outgoing ） |
| `in` | 获取指向该节点的节点（ incoming ） |
| `both` | 双向 |

**请求示例**:

```json
{
  "repo_id": "my-project-123",
  "queries": [
    {"node_id": "module_my-project_auth", "rel_type": "BELONG_TO", "direction": "in"},
    {"node_id": "file_main.py", "rel_type": "CONTAIN", "direction": "out"},
    {"node_id": "class_order_001", "rel_type": "CONTAIN", "direction": "out", "returns": ["node_id", "name", "summary"]}
  ]
}
```

**返回值**: JSON 字符串

```json
{
  "repo_id": "my-project-123",
  "results": [
    {
      "node_id": "module_my-project_auth",
      "rel_type": "BELONG_TO",
      "direction": "in",
      "related_nodes": [
        {
          "node_id": "workflow_login",
          "name": "User Login Flow",
          "node_type": "Workflow",
          "summary": "用户输入凭证 -> 验证 -> 生成 Token",
          "description": "用户登录流程"
        }
      ]
    },
    {
      "node_id": "file_main.py",
      "rel_type": "CONTAIN",
      "direction": "out",
      "related_nodes": [
        {
          "node_id": "class_order_001",
          "name": "OrderService",
          "node_type": "Class",
          "summary": "订单核心业务服务类",
          "description": ""
        }
      ]
    }
  ]
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |
| results | array | 批量查询结果 |

**results 数组元素说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| node_id | string | 查询的节点 ID |
| rel_type | string | 关系类型 |
| direction | string | 关系方向 |
| error | string | 错误信息（失败时返回） |
| related_nodes | array | 关联节点列表 |

**related_nodes 数组元素说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| node_id | string | 节点唯一标识 |
| name | string | 节点名称 |
| node_type | string | 节点类型 |
| summary | string | 节点摘要 |
| description | string | 节点描述（如有） |

---

### 依赖关系

#### get_node_dependencies

批量获取节点的依赖关系图，支持为不同节点指定不同深度。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| queries | array | 是 | 查询参数列表 |

**queries 数组元素说明**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| node_id | string | 是 | 节点 ID |
| depth | int | 否 | 依赖深度，默认 1，最大建议 3 |

**请求示例**:

```json
{
  "queries": [
    {"node_id": "class_auth_001", "depth": 2},
    {"node_id": "class_user_001", "depth": 1}
  ]
}
```

**返回值**: JSON 字符串

```json
{
  "results": [
    {
      "node_id": "class_auth_001",
      "depth": 2,
      "dependencies": [
        {
          "source": {"id": "class_auth_001", "labels": ["Class"]},
          "target": {"id": "class_user_001", "labels": ["Class"]},
          "relationships": ["CALL"],
          "distance": 1
        }
      ]
    },
    {
      "node_id": "class_user_001",
      "depth": 1,
      "dependencies": [...]
    }
  ]
}
```

#### get_all_nodes

获取仓库中所有指定类型的节点列表，支持同时查询多种类型。

**适用场景**：需要"枚举"所有节点的场景，例如生成文档段落标题列表、获取完整的方法清单/类清单/模块清单。如果需要获取节点详情（如代码内容、详细摘要），获取 `node_id` 后请配合 `batch_get_node_details` 使用。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| node_types | array[string] | 否 | 节点类型列表，决定返回哪些类型的节点。默认 `["File", "Class", "Method"]` |
| returns | array[string] | 否 | 指定返回字段列表，如 `["node_id", "name", "summary"]`，减少 token 消耗。默认返回全部字段 |

**node_types 枚举值**:

| 枚举值 | 说明 |
|--------|------|
| `File` | 文件节点 |
| `Class` | 类节点 |
| `Method` | 方法节点 |
| `Module` | 功能模块节点 |
| `Workflow` | 工作流节点 |
| `Directory` | 目录节点 |

可传入多个类型，如 `["Class", "Method"]`，返回结果按类型混合排序。

**returns 可选字段**:

| 字段 | 说明 |
|------|------|
| `node_id` | 节点唯一标识 |
| `name` | 节点名称 |
| `node_type` | 节点类型 |
| `file_path` | 所属文件路径 |
| `summary` | 节点摘要 |
| `language` | 编程语言 |

**请求示例**:

```json
{
  "repo_id": "my-project-123",
  "node_types": ["Method"],
  "returns": ["node_id", "name", "summary"]
}
```

**返回值**: JSON 字符串

```json
{
  "repo_id": "my-project-123",
  "total": 150,
  "nodes": [
    {
      "node_id": "method_my-project_src_auth_service.py_login",
      "name": "login",
      "node_type": "Method",
      "file_path": "src/auth/service.py",
      "summary": "用户登录验证方法",
      "language": "python"
    },
    {
      "node_id": "method_my-project_src_utils_helper.py_hash_password",
      "name": "hash_password",
      "node_type": "Method",
      "file_path": "src/utils/helper.py",
      "summary": "密码哈希处理方法",
      "language": "python"
    }
  ]
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |
| total | int | 节点总数 |
| nodes | array | 节点列表 |

**nodes 数组元素说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| node_id | string | 节点唯一标识 |
| name | string | 节点名称 |
| node_type | string | 节点类型（File / Class / Method / Module / Workflow / Directory） |
| file_path | string | 所属文件路径 |
| summary | string | 节点摘要（如有） |
| language | string | 编程语言（如有） |

**说明**:
- `node_types` 支持同时传入多种类型，如 `["Class", "Method"]`，返回结果按类型混合排序
- 使用 `returns` 参数可以只返回需要的字段，显著减少 token 消耗
- 如需获取节点的完整源码等详细信息，请配合 `batch_get_node_details` 工具使用

---

### 图片 URL 获取

#### batch_get_image_urls

根据节点 ID 列表批量获取节点对应图片的可访问 URL。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| node_ids | array[string] | 是 | 节点 ID 列表 |

**请求示例**:

```json
{
  "repo_id": "my-project-123",
  "node_ids": [
    "method_my-project_src_stm32f10x_tim_c_TIM_DeInit",
    "method_my-project_src_stm32f10x_tim_c_TIM_TimeBaseInit"
  ]
}
```

**返回值**: JSON 字符串

```json
{
  "repo_id": "my-project-123",
  "success": true,
  "total": 2,
  "success_count": 2,
  "failed_count": 0,
  "images": [
    {
      "node_id": "method_my-project_src_stm32f10x_tim_c_TIM_DeInit",
      "node_name": "TIM_DeInit",
      "node_type": "Method",
      "success": true,
      "url": "http://localhost:8000/static/my-project-123/image/Libraries_STM32F10x_StdPeriph_Driver_src_stm32f10x_tim_c_TIM_DeInit__L1.svg"
    },
    {
      "node_id": "method_my-project_src_stm32f10x_tim_c_TIM_TimeBaseInit",
      "node_name": "TIM_TimeBaseInit",
      "node_type": "Method",
      "success": true,
      "url": "http://localhost:8000/static/my-project-123/image/Libraries_STM32F10x_StdPeriph_Driver_src_stm32f10x_tim_c_TIM_TimeBaseInit__L2.svg"
    }
  ]
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |
| success | boolean | 是否有至少一个成功 |
| total | int | 请求的节点 ID 总数 |
| success_count | int | 成功获取 URL 的数量 |
| failed_count | int | 失败的数量 |
| images | array | 每个节点的图片 URL 结果 |

**images 数组元素说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| node_id | string | 节点 ID |
| node_name | string | 节点名称 |
| node_type | string | 节点类型 |
| success | boolean | 是否成功 |
| url | string | 图片的完整可访问 URL（优先 SVG 格式） |
| error | string | 错误信息（失败时返回）|

**说明**:
- 根据节点 ID 查询节点的 `image` 属性，构建完整的可访问 URL
- 返回的 URL 可直接在浏览器或 Markdown 中使用
- 该工具会查询节点是否存在及其图片属性

---

### 节点详情查询

#### batch_get_node_details

批量根据节点 ID 获取节点的完整属性信息，包括源码、摘要、文档字符串、文件路径等。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| node_ids | array[string] | 是 | 节点 ID 列表 |

**请求示例**:

```json
{
  "repo_id": "my-project-123",
  "node_ids": [
    "class_order_001",
    "method_order_001_create"
  ]
}
```

**返回值**: JSON 字符串

```json
{
  "repo_id": "my-project-123",
  "total": 2,
  "success_count": 2,
  "failed_count": 0,
  "nodes": [
    {
      "node_id": "class_order_001",
      "name": "OrderService",
      "node_type": "Class",
      "file_path": "src/order/service.py",
      "code": "public class OrderService { ... }",
      "summary": "订单核心业务服务类",
      "docstring": "处理订单相关业务逻辑的服务类",
      "language": "java",
      "suffix": "java",
      "success": true
    },
    {
      "node_id": "method_order_001_create",
      "name": "createOrder",
      "node_type": "Method",
      "file_path": "src/order/service.py",
      "code": "public Order createOrder(OrderRequest req) { ... }",
      "summary": "创建订单的核心方法",
      "docstring": "",
      "language": "java",
      "suffix": "java",
      "success": true
    }
  ]
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| repo_id | string | 仓库 ID |
| total | int | 请求的节点 ID 总数 |
| success_count | int | 成功获取详情的节点数量 |
| failed_count | int | 失败的节点数量 |
| nodes | array | 每个节点的详情结果 |

**nodes 数组元素说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| node_id | string | 节点唯一标识 |
| name | string | 节点名称 |
| node_type | string | 节点类型（File / Class / Method 等） |
| file_path | string | 节点所属文件路径 |
| code | string | 节点源码内容（类或方法的完整代码） |
| summary | string | 节点摘要 |
| docstring | string | 文档字符串（如有） |
| language | string | 编程语言 |
| suffix | string | 文件后缀 |
| success | boolean | 是否成功获取 |
| error | string | 错误信息（失败时返回） |

**说明**:
- 底层使用单次 Cypher 查询批量获取，性能优于循环单条查询
- 返回结果按请求传入的 `node_ids` 顺序排列
- 若某个节点不存在，该条目会返回 `success: false` 和 `error` 信息，不影响其他节点
- 对于 `File` 节点，`code` 字段包含文件完整源码
- 对于 `Class` / `Method` 节点，`code` 字段包含该类或方法的源码片段

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

### 节点模型

#### Repository 节点

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 节点唯一标识，格式为 `repo_{repo_name}` |
| name | string | 仓库名称 |
| type | string | 节点类型，固定为 "Repository" |
| repoId | string | 初始化请求传入的业务仓库 ID |
| path | string | 仓库根目录的绝对路径 |
| createdAt | string | 创建时间 (ISO 8601) |
| updatedAt | string | 更新时间 (ISO 8601) |
| totalFiles | int | 仓库内所有文件总数 |
| totalCodeFiles | int | 被识别为代码的文件数（被 Tree-sitter 解析） |
| totalLines | int | 代码文件的总行数累加 |
| totalSize | int | 所有文件的总大小（字节） |
| languages | array[string] | 检测到的编程语言列表（去重排序） |
| languageDistribution | object | 各编程语言对应的代码文件数量，如 `{"python": 50, "java": 30}` |

**说明**:
- `totalLines` 仅累加代码文件行数，排除非代码文件（如图片、二进制资源），避免干扰规模评估
- `totalSize` 累加所有文件大小，反映仓库整体磁盘占用和克隆体积
- 统计信息在 `structure_graph_build` 阶段遍历文件系统时实时汇总，初始化完成后即可通过 Repository 节点查询

---

#### Method 节点

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 节点唯一标识 |
| name | string | 方法名称 |
| type | string | 节点类型，固定为 "Method" |
| filePath | string | 所属文件路径 |
| startLine | int | 起始行号 |
| endLine | int | 结束行号 |
| language | string | 编程语言 |
| code | string | 方法源代码 |
| summary | string | 方法摘要说明 |
| docstring | string | 文档字符串 |
| classId | string | 所属类ID（如有） |
| image | string | **流程图图片URL**（如: `http://localhost:8000/static/{repo_id}/image/{filename}.svg`） |

**说明**: 
- `image` 字段存储的是可直接访问的完整URL，不再是单纯的图片ID
- 支持 SVG 和 PNG 两种格式
- 在 Markdown 中可直接使用 `![流程图](image_url)` 展示

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
FLOWCHART_IMAGE_DIR=app/data             # 相对于项目根目录的路径（不要以./开头）
FLOWCHART_BATCH_SIZE=50

# 静态文件服务配置
PUBLIC_BASE_URL=http://localhost:8000    # 公共服务基础URL
STATIC_FILES_PATH=app/data               # 相对于项目根目录的路径（不要以./开头）
STATIC_FILES_URL=/static                 # 静态文件URL前缀
```
