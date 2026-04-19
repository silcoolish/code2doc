# 文档处理Agent服务 API文档

> **服务名称**: doc-handle-agent  
> **版本**: 1.1.0  
> **描述**: 基于LangGraph的智能文档生成服务

---

## 目录

- [基础信息](#基础信息)
- [API端点概览](#api端点概览)
- [请求/响应模型](#请求响应模型)
- [API详情](#api详情)
- [错误处理](#错误处理)
- [配置说明](#配置说明)

---

## 基础信息

### 基础URL

```
http://localhost:8001/api/v1
```

### 健康检查

```
GET /health
```

**响应示例**:
```json
{
  "status": "healthy",
  "service": "doc-handle-agent"
}
```

### 根路径

```
GET /
```

**响应示例**:
```json
{
  "service": "doc-handle-agent",
  "version": "1.1.0",
  "docs": "/docs"
}
```

---

## API端点概览

| 方法 | 端点 | 描述 | 标签 |
|------|------|------|------|
| POST | `/documents/generate` | 启动文档生成流程 | documents |
| GET | `/documents/active` | 列出所有活动的生成任务 | documents |
| GET | `/documents/status` | 获取系统状态 | documents |
| GET | `/documents/{flow_id}/progress` | 获取文档生成进度 | progress |
| POST | `/documents/{flow_id}/cancel` | 取消文档生成任务 | progress |

---

## 请求/响应模型

### GenerateDocumentRequest

生成文档请求参数

| 字段 | 类型 | 必需 | 描述 |
|------|------|------|------|
| repo_id | string | 是 | 仓库ID |
| template_id | string | 是 | 文档模板ID |

**请求示例**:
```json
{
  "repo_id": "my-repo-123",
  "template_id": "design-doc-template"
}
```

---

### GenerateDocumentResponse

生成文档响应

| 字段 | 类型 | 描述 |
|------|------|------|
| flow_id | string | 流程ID，用于后续查询进度 |
| status | string | 当前状态(pending/running/completed/failed) |
| repo_id | string | 仓库ID |
| template_id | string | 文档模板ID |
| document_id | string \| null | 生成的文档ID |
| output_path | string \| null | 输出路径（向后兼容） |
| created_at | string | 创建时间(ISO 8601格式) |

**响应示例**:
```json
{
  "flow_id": "doc-gen-abc123",
  "status": "running",
  "repo_id": "my-repo-123",
  "template_id": "design-doc-template",
  "document_id": null,
  "output_path": null,
  "created_at": "2024-01-15T10:30:00"
}
```

---

### GenerationProgressResponse

生成进度响应

| 字段 | 类型 | 描述 |
|------|------|------|
| flow_id | string | 流程ID |
| repo_id | string | 仓库ID |
| status | string | 当前状态 |
| progress | float | 进度百分比(0-100) |
| current_step | int | 当前步骤 |
| total_steps | int | 总步骤 |
| message | string | 状态消息 |
| output_path | string \| null | 输出文件路径 |
| error | string \| null | 错误信息 |

**响应示例**:
```json
{
  "flow_id": "doc-gen-abc123",
  "repo_id": "my-repo-123",
  "status": "running",
  "progress": 45.5,
  "current_step": 5,
  "total_steps": 11,
  "message": "正在生成内容: 系统架构设计",
  "output_path": null,
  "error": null
}
```

---

### SystemStatusResponse

系统状态响应

| 字段 | 类型 | 描述 |
|------|------|------|
| status | string | 系统状态(running/idle) |
| active_generations | int | 活动生成任务数 |
| version | string | 版本号 |

**响应示例**:
```json
{
  "status": "running",
  "active_generations": 2,
  "version": "1.1.0"
}
```

---

### ActiveGenerationInfo

活动生成任务信息

| 字段 | 类型 | 描述 |
|------|------|------|
| flow_id | string | 流程ID |
| status | string \| null | 当前状态 |

---

## API详情

### 1. 启动文档生成

```
POST /api/v1/documents/generate
```

启动一个新的文档生成流程。系统会根据模板文件中的占位符，结合仓库代码信息，使用LLM生成完整文档。

#### 请求头

| 头信息 | 值 |
|--------|-----|
| Content-Type | application/json |

#### 请求体

见 [GenerateDocumentRequest](#generatedocumentrequest)

#### 响应

**200 OK**: 成功启动生成流程  
见 [GenerateDocumentResponse](#generatedocumentresponse)

**400 Bad Request**: 参数无效或文件不存在
```json
{
  "detail": "Template file not found: ./templates/不存在的模板.docx"
}
```

**500 Internal Server Error**: 启动生成失败
```json
{
  "detail": "Failed to start generation: 错误详情"
}
```

#### cURL示例

```bash
curl -X POST "http://localhost:8001/api/v1/documents/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_id": "my-project",
    "template_id": "design-doc-template"
  }'
```

---

### 2. 获取生成进度

```
GET /api/v1/documents/{flow_id}/progress
```

获取指定生成任务的当前进度和状态。

#### 路径参数

| 参数 | 类型 | 描述 |
|------|------|------|
| flow_id | string | 流程ID，由 `/generate` 接口返回 |

#### 响应

**200 OK**: 成功获取进度  
见 [GenerationProgressResponse](#generationprogressresponse)

**404 Not Found**: 流程不存在
```json
{
  "detail": "Generation flow not found: doc-gen-xxx"
}
```

#### cURL示例

```bash
curl "http://localhost:8001/api/v1/documents/doc-gen-abc123/progress"
```

---

### 3. 列出活动生成任务

```
GET /api/v1/documents/active
```

获取所有当前正在运行或待处理的生成任务列表。

#### 响应

**200 OK**: 成功获取列表
```json
[
  {
    "flow_id": "doc-gen-abc123",
    "status": "running"
  },
  {
    "flow_id": "doc-gen-def456",
    "status": "pending"
  }
]
```

#### cURL示例

```bash
curl "http://localhost:8001/api/v1/documents/active"
```

---

### 4. 获取系统状态

```
GET /api/v1/documents/status
```

获取系统的整体运行状态。

#### 响应

**200 OK**: 成功获取状态  
见 [SystemStatusResponse](#systemstatusresponse)

#### cURL示例

```bash
curl "http://localhost:8001/api/v1/documents/status"
```

---

### 5. 取消生成任务

```
POST /api/v1/documents/{flow_id}/cancel
```

取消正在运行的文档生成任务。

#### 路径参数

| 参数 | 类型 | 描述 |
|------|------|------|
| flow_id | string | 流程ID |

#### 响应

**200 OK**: 成功取消
```json
{
  "flow_id": "doc-gen-abc123",
  "cancelled": true,
  "message": "Generation cancelled successfully"
}
```

**404 Not Found**: 流程不存在
```json
{
  "detail": "Generation flow not found: doc-gen-xxx"
}
```

**400 Bad Request**: 无法取消
```json
{
  "detail": "Failed to cancel generation or generation already completed"
}
```

#### cURL示例

```bash
curl -X POST "http://localhost:8001/api/v1/documents/doc-gen-abc123/cancel"
```

---

## 错误处理

### HTTP状态码

| 状态码 | 描述 | 场景 |
|--------|------|------|
| 200 | OK | 请求成功 |
| 400 | Bad Request | 请求参数无效、文件不存在 |
| 404 | Not Found | 流程ID不存在 |
| 500 | Internal Server Error | 服务器内部错误 |

### 错误响应格式

所有错误响应均遵循以下格式：

```json
{
  "detail": "错误描述信息"
}
```

---

## 配置说明

### 环境变量

| 变量名 | 默认值 | 描述 |
|--------|--------|------|
| APP_NAME | doc-handle-agent | 应用名称 |
| APP_HOST | 0.0.0.0 | 服务监听地址 |
| APP_PORT | 8001 | 服务端口 |
| DEBUG | false | 调试模式 |
| LLM_PROVIDER | qwen | LLM提供商 |
| DASHSCOPE_API_KEY | - | DashScope API密钥 |
| DASHSCOPE_BASE_URL | https://dashscope.aliyuncs.com/api/v1 | DashScope基础URL |
| LLM_MODEL | qwen-max-latest | LLM模型名称 |
| MCP_SERVER_URL | http://localhost:8000/sse | MCP服务器URL |
| TEMPLATE_DIR | ./templates | 模板目录 |
| OUTPUT_DIR | ./output | 输出目录 |
| LOG_DIR | ./log | 日志目录 |
| TEMP_DIR | ./temp | 临时目录 |
| LOG_LEVEL | INFO | 日志级别 |

### 配置文件

`.env` 文件示例：

```bash
# FastAPI配置
APP_NAME=doc-handle-agent
APP_HOST=0.0.0.0
APP_PORT=8001
DEBUG=false

# LLM配置
LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=your-api-key-here
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
LLM_MODEL=qwen-max-latest

# MCP配置
MCP_SERVER_URL=http://localhost:8000/sse

# 路径配置
TEMPLATE_DIR=./templates
OUTPUT_DIR=./output
LOG_DIR=./log
TEMP_DIR=./temp

# 日志配置
LOG_LEVEL=INFO
```

---

## 模板格式说明

### 模板占位符语法

模板使用特殊语法标记需要LLM生成的内容：

```
{{标题:提示词[约束条件]}}
```

**示例**:
```
{{项目概述:请用200-300字描述项目的整体概况[is_list=true]}}
{{技术架构:描述系统的技术架构，包含核心组件和它们之间的关系[min_length=500,max_length=1000]}}
```

### 约束条件

| 约束 | 说明 | 示例 |
|------|------|------|
| is_list | 生成列表格式 | `[is_list=true]` |
| min_length | 最小长度 | `[min_length=200]` |
| max_length | 最大长度 | `[max_length=500]` |
| example | 参考示例 | `[example=参考文本]` |

---

## 流程状态说明

| 状态 | 描述 |
|------|------|
| pending | 等待开始 |
| running | 正在生成 |
| completed | 生成完成 |
| failed | 生成失败 |
| cancelled | 已取消 |
