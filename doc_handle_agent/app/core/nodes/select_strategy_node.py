"""内容生成策略选择节点."""

from app.domain.content_generator import ContentGenerator
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)


class SelectStrategyNode(WorkflowNode):
    """内容生成策略选择节点.

    根据预估token数和模型上下文限制，选择最适合的生成策略。
    纯计算节点，不涉及LLM调用。
    """

    def __init__(self, content_generator: ContentGenerator):
        self.content_generator = content_generator

    @property
    def name(self) -> str:
        return "select_strategy"

    async def execute(self, state: AgentState) -> AgentState:
        """选择生成策略.

        将选中的策略名称和预估token数写入state。
        """
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
            if reporter:
                await reporter.report_percent(100, f"策略已选择: {strategy_name}")
            else:
                state["message"] = (
                    f"策略已选择: {strategy_name}, "
                    f"预估token: {estimated_tokens}, "
                    f"共{len(blocks)}个内容块"
                )

            logger.info(
                "select_strategy_success",
                strategy_name=strategy_name,
                estimated_tokens=estimated_tokens,
                block_count=len(blocks),
            )

        except Exception as e:
            logger.error(
                "select_strategy_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["selected_strategy"] = "batched_generation"
            state["estimated_tokens"] = 0
            state["message"] = f"策略选择失败，降级为分批生成: {str(e)}"

        return state
