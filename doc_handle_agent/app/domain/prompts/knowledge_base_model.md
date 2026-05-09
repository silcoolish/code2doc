# 知识底座图模型与工具指南

知识底座使用 Neo4j 图数据库存储代码结构，理解数据模型有助于你精准选择工具和参数。

## 节点类型

| 节点类型 | 标签 | 关键字段 | 说明 |
|----------|------|----------|------|
| Repository | Repository | totalFiles, totalCodeFiles, totalLines, totalSize, languages, languageDistribution | 仓库根节点，包含规模统计 |
| Directory | Directory | path | 文件系统目录 |
| File | File | path, code, summary, suffix, fileType | 文件节点，code 为完整文件内容 |
| Class | Class | filePath, startLine, endLine, code, summary, docstring, realType, language | 类/结构体/接口/枚举 |
| Method | Method | filePath, startLine, endLine, code, summary, docstring, language, classId, image | 方法/函数，image 为流程图图片ID |
| Module | Module | summary, detail, keywords, confidence | 功能模块（语义抽象），detail 为详细设计说明 |
| Workflow | Workflow | summary, detail, keywords, confidence, moduleId | 业务流程（语义抽象），detail 为详细设计说明 |

**重点提示**：
- File 节点的 `code` 是完整文件内容；Class/Method 的 `code` 是源码片段
- Module/Workflow 有 `detail` 字段（详细设计说明），生成模块/流程文档时应优先取此字段，而非仅用 `summary`
- Method 的 `image` 字段存储流程图的图片ID（文件名），可通过 `/images/{repo_id}/{image_id}` 下载

## 关系类型

| 关系类型 | 方向示例 | 语义说明 |
|----------|----------|----------|
| CONTAIN | Repository → Directory → File → Class/Method | 包含关系，构成层级结构 |
| BELONG_TO | Workflow → Module | 属于关系，Workflow 属于某个 Module |
| CALL | Method → Method | 调用关系，A 方法调用 B 方法 |
| USE | File → File | 使用关系，A 文件引入/使用了 B 文件 |

**方向说明**：
- `direction="out"`：获取该节点指向的节点（ outgoing ）
- `direction="in"`：获取指向该节点的节点（ incoming ）
- `direction="both"`：双向

## 常用字段与 returns 裁剪

| 字段名 | 存在于 | 用途 | 何时需要 |
|--------|--------|------|----------|
| code | File, Class, Method | 源代码 | 需要引用源码时 |
| summary | 所有节点 | LLM 生成的摘要 | 快速了解节点功能 |
| docstring | Class, Method | 文档字符串 | 生成 API 文档时 |
| detail | Module, Workflow | 详细设计说明 | 生成模块/流程文档时（优先） |
| file_path / path | File, Class, Method, Directory | 文件/目录路径 | 定位代码位置 |
| language | Class, Method | 编程语言 | 多语言项目区分 |
| name | 所有节点 | 节点名称 | always needed |
| node_id / id | 所有节点 | 唯一标识 | 用于后续工具调用 |

**returns 使用建议**：
- 只需列表展示：`returns=["node_id", "name"]`
- 需要生成描述段落：`returns=["node_id", "name", "summary"]`
- 需要源码分析：`returns=["node_id", "name", "code", "docstring"]`
- Module/Workflow 文档：`returns=["node_id", "name", "summary", "detail"]`

## 工具选择决策树

根据你的需求按以下逻辑选择工具：

**1. 了解仓库整体规模**
- `get_repo_stats(repo_id)` → 返回 scale(small/medium/large)、文件数、代码行数、语言分布

**2. 了解项目文件组织结构**
- `get_project_structure(repo_id)` → 返回目录和文件列表

**3. 查找节点（不知道确切名称，只有功能描述）**
- `search_nodes(search_mode="semantic", node_types=["File","Class","Method"] 或 ["Module","Workflow"])` → 拿到 node_id

**4. 查找节点（知道确切名称）**
- `search_nodes(search_mode="name", fuzzy=true/false)` → 拿到 node_id

**5. 枚举某类所有节点**
- `get_all_nodes(node_types=["Method"] / ["Class"] / ["Module"] / ["File"])` → 返回节点列表，取 `name` 字段

**6. 获取节点详情（已知 node_id）**
- `batch_get_node_details(node_ids=[...], returns=[...])`
  - 需要源码：`returns=["node_id","name","code"]`
  - 需要摘要：`returns=["node_id","name","summary"]`
  - Module/Workflow 文档：`returns=["node_id","name","summary","detail"]`

**7. 获取关联节点（已知 node_id）**
- `get_related_nodes(node_id=..., rel_type=..., direction=...)`
  - 文件包含的类/方法：`rel_type="CONTAIN", direction="out"`
  - 模块包含的工作流：`rel_type="BELONG_TO", direction="in"`
  - 方法调用链：`rel_type="CALL", direction="out"`

**8. 分析模块间依赖关系**
- `get_node_dependencies(node_id=..., depth=1/2)` → 返回 source/target/relationships/distance

**9. 获取流程图/架构图图片ID**
- `batch_get_image_ids(node_ids=[...])` → 返回图片ID（如 `xxx.svg`），可通过 `/images/{repo_id}/{image_id}` 下载

**重要提示**：
- 优先使用 `returns` 参数裁剪字段，显著减少 token 消耗
- `search_nodes` 的语义搜索适合找"做某件事"的代码；名称搜索适合快速定位已知类名/方法名
- 拿到 node_id 后，尽量用 `returns` 只取需要的字段，不要默认取回完整 `code`
