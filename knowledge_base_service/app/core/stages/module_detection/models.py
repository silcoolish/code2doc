"""模块检测策略相关数据模型."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FileCluster:
    """文件簇数据类.

    表示通过预聚类算法得到的一组相关文件。

    Attributes:
        id: 簇唯一标识符
        file_ids: 包含的文件ID列表
        internal_edges: 簇内部依赖边 (source, target, weight)
        external_edges: 簇外部依赖边 (source, target, weight)
        directory_prefix: 主要目录前缀
        metadata: 额外元数据
    """

    id: str
    file_ids: List[str] = field(default_factory=list)
    internal_edges: List[Tuple[str, str, int]] = field(default_factory=list)
    external_edges: List[Tuple[str, str, int]] = field(default_factory=list)
    directory_prefix: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """验证数据完整性."""
        if not self.id:
            raise ValueError("FileCluster id cannot be empty")

    @property
    def file_count(self) -> int:
        """获取文件数量."""
        return len(self.file_ids)

    @property
    def internal_dependency_count(self) -> int:
        """获取内部依赖边数量."""
        return len(self.internal_edges)

    @property
    def external_dependency_count(self) -> int:
        """获取外部依赖边数量."""
        return len(self.external_edges)


@dataclass
class WorkflowInfo:
    """工作流信息数据类.

    Attributes:
        name: 工作流名称
        description: 工作流简述
        detail: 工作流详细说明
        files: 关联的文件路径列表
        confidence: 置信度 (0-1)
    """

    name: str
    description: str = ""
    detail: str = ""
    files: List[str] = field(default_factory=list)
    confidence: float = 0.8


@dataclass
class ModuleInfo:
    """模块信息数据类.

    Attributes:
        name: 模块名称
        description: 模块简述
        detail: 模块详细说明
        files: 关联的文件路径列表
        workflows: 模块内的工作流列表
        confidence: 置信度 (0-1)
        cross_module_deps: 跨模块依赖关系
    """

    name: str
    description: str = ""
    detail: str = ""
    files: List[str] = field(default_factory=list)
    workflows: List[WorkflowInfo] = field(default_factory=list)
    confidence: float = 0.8
    cross_module_deps: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ClusterModuleResult:
    """簇级模块检测结果.

    Attributes:
        cluster_id: 来源簇ID
        modules: 检测到的模块列表
        metadata: 额外元数据
    """

    cluster_id: str
    modules: List[ModuleInfo] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def module_count(self) -> int:
        """获取模块数量."""
        return len(self.modules)


@dataclass
class MergedModule:
    """合并后的模块数据类.

    跨簇合并后的最终模块表示。

    Attributes:
        id: 模块唯一标识符
        name: 模块名称
        description: 模块简述
        detail: 模块详细说明
        file_ids: 关联的文件ID列表
        source_clusters: 来源簇ID列表
        workflows: 工作流列表
        confidence: 综合置信度
        merged_from: 合并来源信息
    """

    id: str
    name: str
    description: str = ""
    detail: str = ""
    file_ids: List[str] = field(default_factory=list)
    source_clusters: List[str] = field(default_factory=list)
    workflows: List[WorkflowInfo] = field(default_factory=list)
    confidence: float = 0.8
    merged_from: List[str] = field(default_factory=list)

    def __post_init__(self):
        """验证数据完整性."""
        if not self.id:
            raise ValueError("MergedModule id cannot be empty")

    @property
    def file_count(self) -> int:
        """获取文件数量."""
        return len(self.file_ids)


@dataclass
class FileDependency:
    """文件依赖关系数据类.

    Attributes:
        source: 源文件ID
        target: 目标文件ID
        weight: 依赖权重（调用次数）
        dep_type: 依赖类型 ("use" | "call" | "both")
    """

    source: str
    target: str
    weight: int = 1
    dep_type: str = "use"

    def to_tuple(self) -> Tuple[str, str, int]:
        """转换为元组表示."""
        return (self.source, self.target, self.weight)
