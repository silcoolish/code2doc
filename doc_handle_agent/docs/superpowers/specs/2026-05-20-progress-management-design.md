# 文档生成进度管理优化设计

## 背景

当前 `doc_handle_agent` 的进度管理基于 LangGraph 的 7 个节点，每个节点映射到固定的全局百分比（10/25/40/55/70/85/95/100）。这种粗粒度模型导致两个核心问题：

1. **进度跳跃**：节点完成时进度一次性跳变，用户在长耗时阶段（如 `generate_blocks`）看到的进度长时间卡死。
2. **无内部可见性**：`generate_blocks` 节点可能生成数十个内容块，但进度始终显示 55%，无法反映实际工作进展。

本次优化仅在 `doc_handle_agent` 侧进行，不涉及 workspace 服务的修改。

## 目标

- 将进度推进粒度从**节点级**下沉到**节点内部级**。
- 让 `generate_blocks` 等长耗时阶段按实际工作量平滑推进进度。
- 保持 API 向后兼容，旧任务和 workspace 轮询无感知。

## 方案概述

采用**分层进度模型（Hierarchical Progress Model）**：

- 引擎为每个节点分配全局权重（总和 100%）。
- 每个节点内部通过 `ProgressReporter` 报告子步骤进度（`report_step` 按计数 或 `report_percent` 按百分比）。
- 引擎负责将节点内部进度换算为全局百分比，保证一致性和单调性。
- 节点无需感知全局上下文，只关心自身工作完成了多少。

## 详细设计

### 1. ProgressReporter 接口

新建 `app/core/progress_reporter.py`：

```python
class ProgressReporter:
    """分层进度报告器——将节点内部进度映射到全局工作流进度."""

    def __init__(self, state, node_name, node_weight, completed_weight):
        self._state = state
        self._node_name = node_name
        self._node_weight = node_weight
        self._completed_weight = completed_weight
        self._lock = asyncio.Lock()

    async def report_step(self, current: int, total: int, message: str | None = None):
        """按工作单元计数报告进度."""
        ratio = current / total if total > 0 else 1.0
        progress = self._completed_weight + self._node_weight * ratio
        await self._update_state(progress, message)

    async def report_percent(self, percent: float, message: str | None = None):
        """按节点内部百分比报告进度（percent 为 0-100）."""
        progress = self._completed_weight + self._node_weight * (percent / 100.0)
        await self._update_state(progress, message)

    async def _update_state(self, progress: float, message: str | None):
        try:
            async with self._lock:
                self._state["progress"] = min(100.0, max(0.0, round(progress, 2)))
                if message:
                    self._state["message"] = message
        except Exception as e:
            logger.warning("progress_report_failed", error=str(e))
```

设计要点：
- 节点只报告内部进度，不感知全局百分比。
- `asyncio.Lock` 保证并发安全（防未来节点内部并行化）。
- 异常吞掉并记录 warning，绝不阻断节点主逻辑。

### 2. 全局权重分配

替换 `DocumentEngine` 中固定的 `_NODE_PROGRESS_MAP`：

```python
_NODE_WEIGHTS = {
    "list_template_block":   0.05,
    "outline_confirmation":  0.05,
    "select_strategy":       0.05,
    "generate_blocks":       0.55,  # 核心耗时阶段
    "create_document":       0.10,
    "process_image_blocks":  0.15,
    "store_block_list":      0.05,
}
```

### 3. 引擎集成

#### 3.1 状态扩展

`AgentState` 增加两个字段：

```python
class AgentState(TypedDict):
    # ... 现有字段 ...
    progress: Optional[float]           # 全局精细进度
    __progress_reporter: Optional[Any]  # 节点内部使用的 reporter
```

#### 3.2 节点包装器注入

修改 `DocumentGenerator._wrap_node()`：

```python
def _wrap_node(self, node: WorkflowNode):
    async def wrapped(state: AgentState) -> AgentState:
        state["current_node"] = node.name

        from app.core.document_engine import DocumentEngine
        from app.core.progress_reporter import ProgressReporter

        node_index = DocumentEngine._NODE_ORDER.index(node.name)
        completed_weight = sum(
            DocumentEngine._NODE_WEIGHTS[DocumentEngine._NODE_ORDER[i]]
            for i in range(node_index)
        )
        reporter = ProgressReporter(
            state=state,
            node_name=node.name,
            node_weight=DocumentEngine._NODE_WEIGHTS[node.name],
            completed_weight=completed_weight,
        )
        state["__progress_reporter"] = reporter

        return await node.execute(state)
    return wrapped
```

#### 3.3 进度查询双路径兼容

修改 `DocumentEngine.get_progress()`：

```python
def get_progress(self, flow_id: str) -> Dict:
    # ... 终态处理不变 ...

    total_steps = len(self._NODE_ORDER)

    if "progress" in state:
        # 新路径：节点已报告精细进度
        progress = state["progress"]
        message = state.get("message", "")
        current_step = self._NODE_ORDER.index(current_node) + 1 if current_node else 0
    else:
        # 旧路径：回退到固定节点映射
        current_step = self._NODE_ORDER.index(current_node) + 1 if current_node else 0
        progress = self._NODE_PROGRESS_MAP.get(current_node, 0)
        message = f"正在{self._NODE_NAME_MAP.get(current_node, current_node)}..."

    return {
        "flow_id": flow_id,
        "repo_id": state["repo_id"],
        "status": status,
        "progress": progress,
        "current_step": current_step,
        "total_steps": total_steps,
        "message": message,
        "document_id": state.get("document_id"),
        "error": error,
    }
```

### 4. 各节点细粒度拆分策略

| 节点 | 权重 | 拆分方式 | 实现要点 |
|---|---|---|---|
| `list_template_block` | 5% | `report_percent` | 开始时 0%，完成后 100% |
| `outline_confirmation` | 5% | `report_percent` | 递归展开，开始时 0%，完成后 100% |
| `select_strategy` | 5% | `report_percent` | 纯计算，完成后 100% |
| `generate_blocks` | **55%** | `report_step` + `report_percent` | **核心优化**：按 template block 计数 |
| `create_document` | 10% | `report_percent` | 调用前 0%，调用后 100% |
| `process_image_blocks` | 15% | `report_step` | 按 image block 计数 |
| `store_block_list` | 5% | `report_percent` | 调用前 0%，调用后 100% |

#### 4.1 generate_blocks（核心）

`ContentGenerator.execute_strategy` 增加可选的 `on_progress` 回调：

```python
async def execute_strategy(
    self,
    strategy_name: str,
    blocks: List[TemplateBlock],
    repo_id: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> List[DocumentBlock]:
```

`GenerateBlocksNode` 中：

```python
reporter = state.get("__progress_reporter")
if reporter:
    await reporter.report_percent(0, "开始生成内容...")

    def on_progress(current: int, total: int):
        asyncio.create_task(reporter.report_step(
            current, total,
            f"正在生成第 {current}/{total} 个内容块..."
        ))

    results = await self.content_generator.execute_strategy(
        strategy_name=strategy_name,
        blocks=blocks,
        repo_id=state["repo_id"],
        on_progress=on_progress,
    )
    await reporter.report_percent(100, "内容生成完成")
else:
    results = await self.content_generator.execute_strategy(...)
```

`BatchedGenerationStrategy.execute` 中，每完成一个 batch 触发回调：

```python
# 替换模板内容并记录已生成 block
for result in batch_results:
    if result.block_id:
        all_template_results.append(result)
        generated_ids.add(result.block_id)
        block = block_map.get(result.block_id)
        if block:
            block.content_text = result.text_content

if on_progress:
    on_progress(len(generated_ids), len(template_blocks))
```

`FullContextStrategy` 一次性完成，不触发中间回调，进度自然从 0% 到 100%。

#### 4.2 process_image_blocks

```python
image_blocks = [b for b in doc_blocks if b.get("blockType") == "image"]
reporter = state.get("__progress_reporter")

for idx, block in enumerate(doc_blocks):
    if block.get("blockType") == "image":
        processed = await self._process_image_block(...)
        if reporter:
            img_idx = sum(1 for b in doc_blocks[:idx+1] if b.get("blockType") == "image")
            await reporter.report_step(
                img_idx, len(image_blocks),
                f"正在处理第 {img_idx}/{len(image_blocks)} 个图片资源..."
            )
```

### 5. API 兼容性

`GenerationProgressResponse`  schema 无需修改：

- `progress: float` — 已有字段，现在值更精细（如 62.35 而非固定 55）。
- `current_step / total_steps` — 保持节点级语义（1-7），不变。
- `message` — 现在包含子步骤信息（如"正在生成第 3/12 个内容块..."）。

workspace 服务对 `doc_handle_agent` 的轮询完全无感知，因为响应结构未变。

### 6. 向后兼容

| 场景 | 行为 |
|---|---|
| 新任务 + 新节点 | `__progress_reporter` 注入，精细进度正常上报 |
| 新任务 + 未改造的旧节点 | 节点不调用 reporter，`get_progress` 回退到旧映射 |
| 旧任务（运行中） | 无 `progress` 字段，`get_progress` 完全走旧逻辑 |
| workspace 轮询 | 无感知 |

### 7. 错误处理

- Reporter 自身异常：吞掉并记录 warning，不阻断节点。
- Progress 越界：`min(100.0, max(0.0, progress))` 钳制。
- 节点异常：现有逻辑不变（设置 `FAILED` + `error`），reporter 不干预。

### 8. 测试策略

| 测试类型 | 内容 |
|---|---|
| 单元测试 | `ProgressReporter.report_step/report_percent` 的全局百分比计算准确性 |
| 单元测试 | 各节点在有/无 reporter 时的行为（mock reporter） |
| 集成测试 | `get_progress` 新路径 vs 旧路径的兼容性验证 |
| 集成测试 | `BatchedGenerationStrategy` 触发 `on_progress` 的时序验证 |

## 文件修改清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `app/core/progress_reporter.py` | 新建 | `ProgressReporter` 类 |
| `app/core/state.py` | 修改 | `AgentState` 增加 `progress` 和 `__progress_reporter` |
| `app/core/generator.py` | 修改 | `_wrap_node` 注入 reporter |
| `app/core/document_engine.py` | 修改 | `_NODE_WEIGHTS` 替换 `_NODE_PROGRESS_MAP`；`get_progress` 双路径 |
| `app/core/nodes/generate_blocks_node.py` | 修改 | 调用 reporter，传入 `on_progress` |
| `app/core/nodes/process_image_blocks_node.py` | 修改 | 按 image block 计数报告 |
| `app/core/nodes/list_template_block_node.py` | 修改 | 标记开始/结束 |
| `app/core/nodes/outline_confirmation_node.py` | 修改 | 标记开始/结束 |
| `app/core/nodes/select_strategy_node.py` | 修改 | 标记完成 |
| `app/core/nodes/create_document_node.py` | 修改 | 标记开始/结束 |
| `app/core/nodes/store_block_list.py` | 修改 | 标记开始/结束 |
| `app/domain/content_generator.py` | 修改 | `execute_strategy` 增加 `on_progress` 参数 |
| `app/domain/generation_strategies.py` | 修改 | `BatchedGenerationStrategy` 触发 `on_progress` |
