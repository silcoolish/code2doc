"""工作流节点抽象基类."""

from abc import ABC, abstractmethod
from typing import Any

from app.core.state import AgentState


class WorkflowNode(ABC):
    """工作流节点抽象基类.

    所有工作流节点必须继承此类，实现execute方法。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """节点名称."""
        ...

    @abstractmethod
    async def execute(self, state: AgentState) -> AgentState:
        """执行节点逻辑.

        Args:
            state: 当前工作流状态

        Returns:
            更新后的工作流状态
        """
        ...

    def __call__(self, state: AgentState) -> Any:
        """使节点实例可直接调用."""
        return self.execute(state)
