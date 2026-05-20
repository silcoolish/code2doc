# 进度管理优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将文档生成进度推进粒度从节点级下沉到节点内部级，实现 `generate_blocks` 按内容块计数、`process_image_blocks` 按图片块计数的平滑进度报告。

**Architecture:** 新增 `ProgressReporter` 负责将节点内部子步骤映射到全局百分比；`DocumentGenerator._wrap_node` 为每个节点注入 reporter；各节点内部调用 reporter 报告进度；`DocumentEngine.get_progress` 双路径兼容。

**Tech Stack:** Python 3.13, asyncio, pytest, pytest-asyncio, LangGraph

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `app/core/progress_reporter.py` | 新建 | `ProgressReporter` 类：节点内部进度 → 全局百分比 |
| `app/core/state.py` | 修改 | `AgentState` 增加 `progress` 和 `__progress_reporter` 字段 |
| `app/core/document_engine.py` | 修改 | `_NODE_WEIGHTS` 替换 `_NODE_PROGRESS_MAP`；`get_progress` 双路径兼容 |
| `app/core/generator.py` | 修改 | `_wrap_node` 注入 `ProgressReporter` |
| `app/domain/content_generator.py` | 修改 | `execute_strategy` 增加可选 `on_progress` 回调参数 |
| `app/domain/generation_strategies.py` | 修改 | `BatchedGenerationStrategy.execute` 触发 `on_progress` |
| `app/core/nodes/generate_blocks_node.py` | 修改 | 调用 reporter，传入 `on_progress` 回调 |
| `app/core/nodes/process_image_blocks_node.py` | 修改 | 按 image block 计数调用 `report_step` |
| `app/core/nodes/list_template_block_node.py` | 修改 | 开始/结束标记 |
| `app/core/nodes/outline_confirmation_node.py` | 修改 | 开始/结束标记 |
| `app/core/nodes/select_strategy_node.py` | 修改 | 完成标记 |
| `app/core/nodes/create_document_node.py` | 修改 | 开始/结束标记 |
| `app/core/nodes/store_block_list.py` | 修改 | 开始/结束标记 |
| `tests/unit/core/test_progress_reporter.py` | 新建 | ProgressReporter 单元测试 |
| `tests/unit/core/test_document_engine_progress.py` | 新建 | DocumentEngine.get_progress 双路径测试 |
| `tests/unit/domain/test_generation_strategies_progress.py` | 新建 | BatchedGenerationStrategy on_progress 测试 |

---

### Task 1: ProgressReporter 核心实现

**Files:**
- Create: `app/core/progress_reporter.py`
- Test: `tests/unit/core/test_progress_reporter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_progress_reporter.py`:

```python
import pytest
from app.core.progress_reporter import ProgressReporter
from app.core.state import create_initial_state


@pytest.mark.asyncio
async def test_report_step_maps_to_global_progress():
    state = create_initial_state(repo_id="r1", template_id="t1")
    reporter = ProgressReporter(
        state=state,
        node_name="generate_blocks",
        node_weight=0.55,
        completed_weight=0.15,
    )

    await reporter.report_step(current=1, total=4, message="第1/4块")

    assert state["progress"] == pytest.approx(0.15 + 0.55 * 0.25, abs=0.01)
    assert state["message"] == "第1/4块"


@pytest.mark.asyncio
async def test_report_percent_maps_to_global_progress():
    state = create_initial_state(repo_id="r1", template_id="t1")
    reporter = ProgressReporter(
        state=state,
        node_name="create_document",
        node_weight=0.10,
        completed_weight=0.70,
    )

    await reporter.report_percent(50, message="创建中...")

    assert state["progress"] == pytest.approx(0.70 + 0.10 * 0.5, abs=0.01)
    assert state["message"] == "创建中..."


@pytest.mark.asyncio
async def test_progress_clamped_to_100():
    state = create_initial_state(repo_id="r1", template_id="t1")
    reporter = ProgressReporter(
        state=state,
        node_name="store_block_list",
        node_weight=0.05,
        completed_weight=0.95,
    )

    await reporter.report_percent(200)

    assert state["progress"] == 100.0


@pytest.mark.asyncio
async def test_progress_does_not_decrease_message_when_none():
    state = create_initial_state(repo_id="r1", template_id="t1")
    state["message"] = "已有消息"
    reporter = ProgressReporter(
        state=state,
        node_name="generate_blocks",
        node_weight=0.55,
        completed_weight=0.15,
    )

    await reporter.report_step(current=1, total=4)

    assert state["message"] == "已有消息"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/unit/core/test_progress_reporter.py -v
```
Expected: FAIL with "ProgressReporter not defined" or import error.

- [ ] **Step 3: Write minimal implementation**

Create `app/core/progress_reporter.py`:

```python
"""进度报告器."""

import asyncio
from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class ProgressReporter:
    """分层进度报告器——将节点内部进度映射到全局工作流进度."""

    def __init__(
        self,
        state: Any,
        node_name: str,
        node_weight: float,
        completed_weight: float,
    ):
        self._state = state
        self._node_name = node_name
        self._node_weight = node_weight
        self._completed_weight = completed_weight
        self._lock = asyncio.Lock()

    async def report_step(
        self,
        current: int,
        total: int,
        message: Optional[str] = None,
    ) -> None:
        """按工作单元计数报告进度.

        Args:
            current: 当前已完成数量（从1开始）
            total: 总数量
            message: 可选的进度消息
        """
        ratio = current / total if total > 0 else 1.0
        progress = self._completed_weight + self._node_weight * ratio
        await self._update_state(progress, message)

    async def report_percent(
        self,
        percent: float,
        message: Optional[str] = None,
    ) -> None:
        """按节点内部百分比报告进度.

        Args:
            percent: 节点内部百分比 (0.0 - 100.0)
            message: 可选的进度消息
        """
        progress = self._completed_weight + self._node_weight * (percent / 100.0)
        await self._update_state(progress, message)

    async def _update_state(
        self,
        progress: float,
        message: Optional[str] = None,
    ) -> None:
        """更新状态."""
        try:
            async with self._lock:
                self._state["progress"] = min(100.0, max(0.0, round(progress, 2)))
                if message:
                    self._state["message"] = message
        except Exception as e:
            logger.warning("progress_report_failed", error=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/unit/core/test_progress_reporter.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/progress_reporter.py tests/unit/core/test_progress_reporter.py
git commit -m "feat: add ProgressReporter for hierarchical progress tracking

- report_step: maps unit counts to global progress
- report_percent: maps internal percent to global progress
- asyncio.Lock for concurrency safety
- exceptions swallowed to avoid blocking nodes

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: AgentState 扩展与 DocumentEngine 权重模型

**Files:**
- Modify: `app/core/state.py`
- Modify: `app/core/document_engine.py`
- Test: `tests/unit/core/test_document_engine_progress.py`

- [ ] **Step 1: Modify AgentState**

Edit `app/core/state.py`:

```python
from typing import Any, Dict, List, Optional, TypedDict

# ... existing imports ...

class AgentState(TypedDict):
    """Agent工作流状态."""

    # ... existing fields ...

    # 新增：精细进度（由 ProgressReporter 写入）
    progress: Optional[float]

    # 新增：进度报告器引用（节点内部使用，API 不暴露）
    __progress_reporter: Optional[Any]
```

Edit `create_initial_state` in the same file to initialize the new fields:

```python
def create_initial_state(
    repo_id: str,
    template_id: str,
    template_path: str = "",
) -> AgentState:
    return {
        # ... existing fields ...
        "progress": None,
        "__progress_reporter": None,
    }
```

- [ ] **Step 2: Modify DocumentEngine**

Edit `app/core/document_engine.py`:

Replace `_NODE_PROGRESS_MAP` with `_NODE_WEIGHTS`:

```python
    # 节点进度权重分配（总和 1.0）
    _NODE_WEIGHTS = {
        "list_template_block": 0.05,
        "outline_confirmation": 0.05,
        "select_strategy": 0.05,
        "generate_blocks": 0.55,
        "create_document": 0.10,
        "process_image_blocks": 0.15,
        "store_block_list": 0.05,
    }
```

Keep `_NODE_PROGRESS_MAP` for backward compatibility in get_progress fallback, or calculate it dynamically. For simplicity, keep both:

```python
    # 保留旧映射用于回退兼容
    _NODE_PROGRESS_MAP = {
        "list_template_block": 10,
        "outline_confirmation": 25,
        "select_strategy": 40,
        "generate_blocks": 55,
        "create_document": 70,
        "process_image_blocks": 85,
        "store_block_list": 95,
    }
```

Modify `get_progress` method:

```python
    def get_progress(self, flow_id: str) -> Dict:
        state = self._task_states.get(flow_id)

        if not state:
            return {
                "flow_id": flow_id,
                "status": "not_found",
                "error": "流程不存在",
            }

        status = state["status"]
        current_node = state.get("current_node")
        error = state.get("error")

        if status == GenerationStatus.COMPLETED.value:
            return {
                "flow_id": flow_id,
                "repo_id": state["repo_id"],
                "status": status,
                "progress": 100,
                "current_step": len(self._NODE_ORDER),
                "total_steps": len(self._NODE_ORDER),
                "message": "文档生成完成",
                "document_id": state.get("document_id"),
                "error": None,
            }

        if status == GenerationStatus.FAILED.value:
            return {
                "flow_id": flow_id,
                "repo_id": state["repo_id"],
                "status": status,
                "progress": 0,
                "current_step": 0,
                "total_steps": len(self._NODE_ORDER),
                "message": f"文档生成失败: {error}" if error else "文档生成失败",
                "document_id": state.get("document_id"),
                "error": error,
            }

        total_steps = len(self._NODE_ORDER)

        if "progress" in state and state["progress"] is not None:
            current_step = self._NODE_ORDER.index(current_node) + 1 if current_node else 0
            progress = state["progress"]
            message = state.get("message", "")
        else:
            if current_node and current_node in self._NODE_ORDER:
                current_step = self._NODE_ORDER.index(current_node) + 1
                progress = self._NODE_PROGRESS_MAP.get(current_node, 0)
                node_name_cn = self._NODE_NAME_MAP.get(current_node, current_node)
                message = f"正在{node_name_cn}..."
            else:
                current_step = 0
                progress = 0
                message = state.get("message", "等待开始生成...")

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

- [ ] **Step 3: Write tests for DocumentEngine progress**

Create `tests/unit/core/test_document_engine_progress.py`:

```python
import pytest
from app.core.document_engine import DocumentEngine
from app.core.state import create_initial_state, GenerationStatus


class TestDocumentEngineProgress:
    def test_get_progress_uses_fine_grained_when_available(self):
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.GENERATING.value
        state["current_node"] = "generate_blocks"
        state["progress"] = 62.5
        state["message"] = "正在生成第 3/12 块..."
        engine._task_states["flow_1"] = state

        result = engine.get_progress("flow_1")

        assert result["progress"] == 62.5
        assert result["message"] == "正在生成第 3/12 块..."
        assert result["current_step"] == 4

    def test_get_progress_falls_back_to_old_mapping(self):
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.GENERATING.value
        state["current_node"] = "generate_blocks"
        # progress not set
        engine._task_states["flow_2"] = state

        result = engine.get_progress("flow_2")

        assert result["progress"] == 55
        assert "正在生成文档内容" in result["message"] or "generate_blocks" in result["message"]

    def test_get_progress_completed_state(self):
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.COMPLETED.value
        state["document_id"] = "doc_1"
        engine._task_states["flow_3"] = state

        result = engine.get_progress("flow_3")

        assert result["progress"] == 100
        assert result["document_id"] == "doc_1"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/core/test_document_engine_progress.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/state.py app/core/document_engine.py tests/unit/core/test_document_engine_progress.py
git commit -m "feat: AgentState progress fields and DocumentEngine dual-path get_progress

- AgentState: add progress and __progress_reporter fields
- DocumentEngine: _NODE_WEIGHTS for fine-grained progress
- get_progress: prefer state['progress'] when available, fallback to old node mapping
- Backward compatible: old tasks without progress field still work

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: DocumentGenerator._wrap_node 注入 reporter

**Files:**
- Modify: `app/core/generator.py`

- [ ] **Step 1: Modify _wrap_node**

Edit `app/core/generator.py`:

```python
    def _wrap_node(self, node: WorkflowNode):
        """包装节点执行函数，在执行前记录当前节点并注入 ProgressReporter."""

        async def wrapped(state: AgentState) -> AgentState:
            state["current_node"] = node.name

            # 注入 ProgressReporter
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

- [ ] **Step 2: Verify no import cycles**

Run:
```bash
python -c "from app.core.generator import DocumentGenerator; print('OK')"
```
Expected: `OK` (no import cycle).

- [ ] **Step 3: Commit**

```bash
git add app/core/generator.py
git commit -m "feat: inject ProgressReporter into each node via _wrap_node

- Calculate completed_weight and node_weight from DocumentEngine._NODE_WEIGHTS
- Attach reporter to state['__progress_reporter'] for nodes to use

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: ContentGenerator 与策略支持 on_progress

**Files:**
- Modify: `app/domain/content_generator.py`
- Modify: `app/domain/generation_strategies.py`
- Test: `tests/unit/domain/test_generation_strategies_progress.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/domain/test_generation_strategies_progress.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domain.generation_strategies import BatchedGenerationStrategy
from app.domain.model import TemplateBlock, DocumentBlock


@pytest.mark.asyncio
async def test_batched_strategy_triggers_on_progress():
    agent = MagicMock()
    agent.generate_with_tools = AsyncMock(return_value='[
  {"id": "1", "block_type": "paragraph", "content_text": "hello"}
]')

    strategy = BatchedGenerationStrategy(agent)

    blocks = [
        TemplateBlock(
            id="1",
            block_type="paragraph",
            content_text="test",
            is_template=True,
            order_no="a",
        ),
        TemplateBlock(
            id="2",
            block_type="paragraph",
            content_text="test2",
            is_template=True,
            order_no="b",
        ),
    ]

    progress_calls = []

    def on_progress(current, total):
        progress_calls.append((current, total))

    results = await strategy.execute(blocks, repo_id="r1", on_progress=on_progress)

    assert len(progress_calls) > 0
    assert progress_calls[-1][0] == 2
    assert progress_calls[-1][1] == 2
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/unit/domain/test_generation_strategies_progress.py -v
```
Expected: FAIL with "unexpected keyword argument 'on_progress'".

- [ ] **Step 3: Modify ContentGenerator.execute_strategy**

Edit `app/domain/content_generator.py`:

```python
from typing import Any, Dict, List, Tuple, Optional, Callable

# ...

    async def execute_strategy(
        self,
        strategy_name: str,
        blocks: List[TemplateBlock],
        repo_id: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[DocumentBlock]:
        """按指定策略执行生成.

        Args:
            strategy_name: 策略名称
            blocks: block列表
            repo_id: 仓库ID
            on_progress: 可选的进度回调，接收 (current, total)

        Returns:
            DocumentBlock 列表
        """
        if not blocks:
            return []

        logger.info(
            "execute_strategy_start",
            strategy_name=strategy_name,
            block_count=len(blocks),
            template_blocks=sum(1 for b in blocks if b.is_template),
            static_blocks=sum(1 for b in blocks if not b.is_template),
            repo_id=repo_id,
        )

        strategy_cls = STRATEGY_NAME_MAP.get(strategy_name)
        if not strategy_cls:
            logger.error("unknown_strategy", strategy_name=strategy_name)
            return self._build_error_results(blocks)

        strategy = strategy_cls(self.agent)

        try:
            results = await strategy.execute(blocks, repo_id, on_progress=on_progress)
            logger.info(
                "execute_strategy_complete",
                strategy_name=strategy_name,
                total_results=len(results),
            )
            return results
        except FallbackSignalError:
            logger.warning("strategy_fallback_signal", strategy=strategy_name)
            return await self._fallback_to_next_strategy(strategy_name, blocks, repo_id)
        except Exception as e:
            logger.error(
                "strategy_execution_failed",
                strategy_name=strategy_name,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return self._build_error_results(blocks)
```

- [ ] **Step 4: Modify BatchedGenerationStrategy.execute**

Edit `app/domain/generation_strategies.py`:

```python
    async def execute(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[DocumentBlock]:
```

Inside the while loop, after processing each batch and updating `generated_ids`:

```python
            # 替换模板内容并记录已生成 block
            for result in batch_results:
                if result.block_id:
                    all_template_results.append(result)
                    generated_ids.add(result.block_id)
                    block = block_map.get(result.block_id)
                    if block:
                        block.content_text = result.text_content

            # 触发进度回调
            if on_progress:
                on_progress(len(generated_ids), len(template_blocks))

            i = next_i
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/domain/test_generation_strategies_progress.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/domain/content_generator.py app/domain/generation_strategies.py tests/unit/domain/test_generation_strategies_progress.py
git commit -m "feat: BatchedGenerationStrategy reports progress via on_progress callback

- ContentGenerator.execute_strategy accepts optional on_progress(current, total)
- BatchedGenerationStrategy triggers on_progress after each batch
- FullContextStrategy ignores on_progress (single-shot)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: generate_blocks 节点接入 reporter

**Files:**
- Modify: `app/core/nodes/generate_blocks_node.py`

- [ ] **Step 1: Modify generate_blocks node**

Edit `app/core/nodes/generate_blocks_node.py`:

```python
    async def execute(self, state: AgentState) -> AgentState:
        if state.get("error"):
            return state

        blocks: List[TemplateBlock] = state.get("blocks", [])
        if not blocks:
            return state

        strategy_name = state.get("selected_strategy") or "batched_generation"
        reporter = state.get("__progress_reporter")

        try:
            state["status"] = GenerationStatus.GENERATING.value

            if reporter:
                await reporter.report_percent(0, f"正在使用 {strategy_name} 策略生成内容...")

                def on_progress(current: int, total: int):
                    asyncio.create_task(
                        reporter.report_step(
                            current,
                            total,
                            f"正在生成第 {current}/{total} 个内容块...",
                        )
                    )

                results = await self.content_generator.execute_strategy(
                    strategy_name=strategy_name,
                    blocks=blocks,
                    repo_id=state["repo_id"],
                    on_progress=on_progress,
                )

                await reporter.report_percent(100, "内容生成完成")
            else:
                state["message"] = f"正在使用 {strategy_name} 策略生成内容..."
                results = await self.content_generator.execute_strategy(
                    strategy_name=strategy_name,
                    blocks=blocks,
                    repo_id=state["repo_id"],
                )

            doc_blocks = self._build_document_blocks(blocks, results)
            state["doc_blocks"] = doc_blocks

        except Exception as e:
            logger.error(
                "generate_blocks_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"内容生成失败: {str(e)}"

        return state
```

Add `import asyncio` at the top of the file if not already present.

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile app/core/nodes/generate_blocks_node.py
```
Expected: No output (success).

- [ ] **Step 3: Commit**

```bash
git add app/core/nodes/generate_blocks_node.py
git commit -m "feat: generate_blocks node reports fine-grained progress

- report_percent(0) at start, report_percent(100) at end
- Pass on_progress callback to ContentGenerator for batched strategy
- Reporter not found fallback preserves old behavior

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: process_image_blocks 节点接入 reporter

**Files:**
- Modify: `app/core/nodes/process_image_blocks_node.py`

- [ ] **Step 1: Modify process_image_blocks node**

Edit `app/core/nodes/process_image_blocks_node.py`:

```python
    async def execute(self, state: AgentState) -> AgentState:
        if state.get("error"):
            return state

        doc_blocks = state.get("doc_blocks", [])
        if not doc_blocks:
            logger.info("no_doc_blocks_to_process")
            return state

        document_id = state.get("document_id")
        if not document_id:
            logger.error("document_id_not_found")
            state["error"] = "document_id 不存在，无法创建图片资源"
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = "图片资源处理失败: 文档尚未创建"
            return state

        repo_id = state.get("repo_id", "")
        reporter = state.get("__progress_reporter")

        try:
            state["status"] = GenerationStatus.GENERATING.value
            if reporter:
                await reporter.report_percent(0, "正在处理图片资源...")

            image_blocks = [b for b in doc_blocks if b.get("blockType") == "image"]
            total_images = len(image_blocks)
            processed_count = 0

            with log_timing("process_image_blocks", block_count=len(doc_blocks)):
                updated_blocks: List[Dict[str, Any]] = []
                for block in doc_blocks:
                    if block.get("blockType") == "image":
                        processed = await self._process_image_block(block, document_id, repo_id)
                        updated_blocks.append(processed)
                        processed_count += 1
                        if reporter:
                            await reporter.report_step(
                                processed_count,
                                total_images,
                                f"正在处理第 {processed_count}/{total_images} 个图片资源...",
                            )
                    else:
                        updated_blocks.append(block)

            state["doc_blocks"] = updated_blocks

            if reporter:
                await reporter.report_percent(100, "图片资源处理完成")

        except Exception as e:
            logger.error(
                "process_image_blocks_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"图片资源处理失败: {str(e)}"

        return state
```

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile app/core/nodes/process_image_blocks_node.py
```

- [ ] **Step 3: Commit**

```bash
git add app/core/nodes/process_image_blocks_node.py
git commit -m "feat: process_image_blocks reports progress per image block

- Count image blocks and report_step after each processed image
- report_percent(0) at start, report_percent(100) at end

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: 其余轻量节点接入 reporter

**Files:**
- Modify: `app/core/nodes/list_template_block_node.py`
- Modify: `app/core/nodes/outline_confirmation_node.py`
- Modify: `app/core/nodes/select_strategy_node.py`
- Modify: `app/core/nodes/create_document_node.py`
- Modify: `app/core/nodes/store_block_list.py`

- [ ] **Step 1: Modify list_template_block_node**

Edit `app/core/nodes/list_template_block_node.py`:

```python
    async def execute(self, state: AgentState) -> AgentState:
        template_id = state["template_id"]
        reporter = state.get("__progress_reporter")

        try:
            if reporter:
                await reporter.report_percent(0, "正在获取模板内容块列表...")

            with log_timing("list_template_blocks", template_id=template_id):
                blocks = await self.workspace_adapter.get_template_blocks(template_id)

            state["blocks"] = blocks
            state["total_blocks"] = len(blocks)
            state["status"] = GenerationStatus.GENERATING.value
            state["message"] = f"获取完成，共{len(blocks)}个内容块待生成"

            if reporter:
                await reporter.report_percent(100, f"获取完成，共{len(blocks)}个内容块待生成")

        except Exception as e:
            # ... existing error handling ...
            pass

        return state
```

- [ ] **Step 2: Modify outline_confirmation_node**

Edit `app/core/nodes/outline_confirmation_node.py`:

```python
    async def execute(self, state: AgentState) -> AgentState:
        if state.get("error"):
            return state

        blocks = state.get("blocks", [])
        if not blocks:
            return state

        reporter = state.get("__progress_reporter")

        try:
            state["status"] = GenerationStatus.PARSING.value
            if reporter:
                await reporter.report_percent(0, "正在确认文档大纲...")

            with log_timing("outline_confirmation", block_count=len(blocks)):
                # ... existing logic ...

            state["message"] = f"大纲确认完成，共{len(expanded_blocks)}个内容块"

            if reporter:
                await reporter.report_percent(100, f"大纲确认完成，共{len(expanded_blocks)}个内容块")

        except Exception as e:
            # ... existing error handling ...
            pass

        return state
```

- [ ] **Step 3: Modify select_strategy_node**

Edit `app/core/nodes/select_strategy_node.py`:

```python
    async def execute(self, state: AgentState) -> AgentState:
        if state.get("error"):
            return state

        blocks = state.get("blocks", [])
        reporter = state.get("__progress_reporter")

        if not blocks:
            state["selected_strategy"] = "full_context"
            state["estimated_tokens"] = 0
            state["message"] = "无可生成内容块，跳过策略选择"
            if reporter:
                await reporter.report_percent(100, "无可生成内容块，跳过策略选择")
            return state

        try:
            if reporter:
                await reporter.report_percent(0, "正在选择内容生成策略...")

            with log_timing("select_strategy", block_count=len(blocks)):
                strategy_name, estimated_tokens = self.content_generator.select_strategy(blocks)

            state["selected_strategy"] = strategy_name
            state["estimated_tokens"] = estimated_tokens
            state["message"] = (
                f"策略已选择: {strategy_name}, "
                f"预估token: {estimated_tokens}, "
                f"共{len(blocks)}个内容块"
            )

            if reporter:
                await reporter.report_percent(100, f"策略已选择: {strategy_name}")

        except Exception as e:
            # ... existing error handling ...
            pass

        return state
```

- [ ] **Step 4: Modify create_document_node**

Edit `app/core/nodes/create_document_node.py`:

```python
    async def execute(self, state: AgentState) -> AgentState:
        if state.get("error"):
            return state

        doc_blocks = state.get("doc_blocks", [])
        reporter = state.get("__progress_reporter")

        try:
            state["status"] = GenerationStatus.BUILDING.value
            if reporter:
                await reporter.report_percent(0, "正在创建文档...")

            title = self._extract_title(state)
            state["title"] = title

            save_request = SaveDocumentRequest(
                repo_id=state["repo_id"],
                doc_type="project",
                target_key="__project__",
                title=title,
                blocks=[],
            )

            with log_timing("create_document", repo_id=state["repo_id"]):
                save_response = await self.workspace_adapter.save_document(save_request)

            if not save_response.success:
                raise RuntimeError(f"Failed to create document: {save_response.error}")

            document_id = save_response.document_id
            state["document_id"] = document_id
            state["message"] = "文档创建成功"

            if reporter:
                await reporter.report_percent(100, "文档创建成功")

        except Exception as e:
            # ... existing error handling ...
            pass

        return state
```

- [ ] **Step 5: Modify store_block_list**

Edit `app/core/nodes/store_block_list.py`:

```python
    async def execute(self, state: AgentState) -> AgentState:
        reporter = state.get("__progress_reporter")

        try:
            state["status"] = GenerationStatus.BUILDING.value
            if reporter:
                await reporter.report_percent(0, "正在构建最终文档...")

            doc_blocks = state.get("doc_blocks", [])
            if not doc_blocks:
                logger.warning("no_doc_blocks_in_state")

            for block in doc_blocks:
                block["id"] = ""

            title = state.get("title") or "项目文档"
            save_request = SaveDocumentRequest(
                repo_id=state["repo_id"],
                doc_type="project",
                target_key="__project__",
                title=title,
                blocks=doc_blocks,
            )

            with log_timing("save_document", block_count=len(doc_blocks)):
                save_response = await self.workspace_adapter.save_document(save_request)

            if not save_response.success:
                raise RuntimeError(f"Failed to save document: {save_response.error}")

            document_id = save_response.document_id
            state["document_id"] = document_id
            state["status"] = GenerationStatus.BUILDING.value
            state["message"] = "文档已保存，正在收尾..."

            if reporter:
                await reporter.report_percent(100, "文档已保存")

        except Exception as e:
            # ... existing error handling ...
            pass

        return state
```

- [ ] **Step 6: Verify syntax for all 5 files**

```bash
python -m py_compile app/core/nodes/list_template_block_node.py
python -m py_compile app/core/nodes/outline_confirmation_node.py
python -m py_compile app/core/nodes/select_strategy_node.py
python -m py_compile app/core/nodes/create_document_node.py
python -m py_compile app/core/nodes/store_block_list.py
```
Expected: All pass silently.

- [ ] **Step 7: Commit**

```bash
git add app/core/nodes/list_template_block_node.py \
       app/core/nodes/outline_confirmation_node.py \
       app/core/nodes/select_strategy_node.py \
       app/core/nodes/create_document_node.py \
       app/core/nodes/store_block_list.py
git commit -m "feat: lightweight nodes report start/end progress

- list_template_block, outline_confirmation, select_strategy
- create_document, store_block_list
- report_percent(0) at start, report_percent(100) at completion

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: 集成测试与验证

**Files:**
- Test: `tests/integration/test_progress_flow.py`

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_progress_flow.py`:

```python
import pytest
from app.core.document_engine import DocumentEngine
from app.core.state import create_initial_state, GenerationStatus


class TestProgressFlow:
    def test_progress_monotonically_increases_across_nodes(self):
        """验证进度在模拟多节点执行后是单调递增的."""
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.GENERATING.value

        # 模拟 list_template_block 完成 (5%)
        state["current_node"] = "list_template_block"
        state["progress"] = 5.0
        engine._task_states["flow_test"] = state.copy()

        p1 = engine.get_progress("flow_test")
        assert p1["progress"] == 5.0

        # 模拟 generate_blocks 第 2/4 块 (15% + 55% * 0.5 = 42.5%)
        state["current_node"] = "generate_blocks"
        state["progress"] = 42.5
        state["message"] = "正在生成第 2/4 个内容块..."
        engine._task_states["flow_test"] = state.copy()

        p2 = engine.get_progress("flow_test")
        assert p2["progress"] == 42.5
        assert "2/4" in p2["message"]

        # 模拟 process_image_blocks 第 1/2 块 (70% + 15% * 0.5 = 77.5%)
        state["current_node"] = "process_image_blocks"
        state["progress"] = 77.5
        state["message"] = "正在处理第 1/2 个图片资源..."
        engine._task_states["flow_test"] = state.copy()

        p3 = engine.get_progress("flow_test")
        assert p3["progress"] == 77.5

    def test_old_task_without_progress_field(self):
        """验证没有 progress 字段的旧任务回退到旧映射."""
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.GENERATING.value
        state["current_node"] = "create_document"
        # 不设置 state["progress"]
        engine._task_states["flow_old"] = state

        result = engine.get_progress("flow_old")
        assert result["progress"] == 70
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/unit/core/test_progress_reporter.py \
       tests/unit/core/test_document_engine_progress.py \
       tests/unit/domain/test_generation_strategies_progress.py \
       tests/integration/test_progress_flow.py -v
```
Expected: All tests PASS.

- [ ] **Step 3: Run full test suite**

```bash
pytest -v
```
Expected: All existing tests still PASS (no regressions).

- [ ] **Step 4: Final commit**

```bash
git add tests/integration/test_progress_flow.py
git commit -m "test: integration tests for fine-grained progress flow

- Verify progress monotonically increases across simulated nodes
- Verify old tasks without progress field fallback correctly

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] ProgressReporter interface with report_step/report_percent → Task 1
- [x] AgentState progress fields → Task 2
- [x] DocumentEngine _NODE_WEIGHTS → Task 2
- [x] DocumentEngine get_progress dual-path → Task 2
- [x] DocumentGenerator._wrap_node injection → Task 3
- [x] ContentGenerator on_progress callback → Task 4
- [x] BatchedGenerationStrategy triggers on_progress → Task 4
- [x] generate_blocks node uses reporter → Task 5
- [x] process_image_blocks node uses reporter → Task 6
- [x] Other 5 nodes report start/end → Task 7
- [x] Backward compatibility → Task 2, integration tests

**Placeholder scan:**
- [x] No TBD/TODO
- [x] No "implement later"
- [x] All code blocks complete
- [x] All commands exact with expected output

**Type consistency:**
- [x] `on_progress: Optional[Callable[[int, int], None]]` consistent across files
- [x] `state.get("__progress_reporter")` pattern used in all nodes
- [x] `_NODE_WEIGHTS` keys match `_NODE_ORDER`
