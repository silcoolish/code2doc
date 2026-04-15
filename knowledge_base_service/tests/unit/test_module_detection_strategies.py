"""模块检测策略单元测试."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from app.core.stages.module_detection.models import (
    FileCluster,
    FileDependency,
    MergedModule,
    ModuleInfo,
    WorkflowInfo,
)
from app.core.stages.module_detection.strategies import (
    ModuleDetectionStrategyFactory,
    SimpleTruncationStrategy,
)
from app.core.stages.module_detection.strategies.clustering import ClusteringStrategy
from app.core.stages.module_detection.strategies.base import ModuleDetectionResult


class TestModuleDetectionStrategyFactory:
    """测试策略工厂."""

    def test_list_strategies(self):
        """测试列出可用策略."""
        strategies = ModuleDetectionStrategyFactory.list_strategies()

        assert "simple" in strategies
        assert "clustering" in strategies
        assert "简单截断策略" in strategies["simple"]
        assert "分层聚类策略" in strategies["clustering"]

    def test_get_simple_strategy(self):
        """测试获取简单策略."""
        strategy = ModuleDetectionStrategyFactory.get("simple")

        assert isinstance(strategy, SimpleTruncationStrategy)
        assert strategy.name == "simple"
        assert strategy.validate_config()

    def test_get_clustering_strategy(self):
        """测试获取聚类策略."""
        strategy = ModuleDetectionStrategyFactory.get("clustering")

        assert isinstance(strategy, ClusteringStrategy)
        assert strategy.name == "clustering"
        assert strategy.validate_config()

    def test_get_strategy_with_custom_config(self):
        """测试获取自定义配置的策略."""
        strategy = ModuleDetectionStrategyFactory.get(
            "simple", max_files=50
        )

        assert strategy.max_files == 50

    def test_get_unknown_strategy(self):
        """测试获取未知策略."""
        with pytest.raises(ValueError) as exc_info:
            ModuleDetectionStrategyFactory.get("unknown")

        assert "Unknown strategy" in str(exc_info.value)

    def test_register_custom_strategy(self):
        """测试注册自定义策略."""

        class CustomStrategy:
            @property
            def name(self):
                return "custom"

            @property
            def description(self):
                return "Custom strategy"

            def validate_config(self):
                return True

        # 清除缓存
        ModuleDetectionStrategyFactory.clear_cache()

        # 注册策略
        ModuleDetectionStrategyFactory.register("custom", CustomStrategy)

        # 获取策略
        strategy = ModuleDetectionStrategyFactory.get("custom")
        assert strategy.name == "custom"


class TestSimpleTruncationStrategy:
    """测试简单截断策略."""

    def test_init_default(self):
        """测试默认初始化."""
        strategy = SimpleTruncationStrategy()

        assert strategy.max_files == 100
        assert strategy.name == "simple"

    def test_init_custom(self):
        """测试自定义初始化."""
        strategy = SimpleTruncationStrategy(max_files=50)

        assert strategy.max_files == 50

    def test_validate_config_valid(self):
        """测试有效配置验证."""
        strategy = SimpleTruncationStrategy(max_files=100)

        assert strategy.validate_config()

    def test_validate_config_invalid(self):
        """测试无效配置验证."""
        strategy = SimpleTruncationStrategy(max_files=0)

        assert not strategy.validate_config()

    def test_build_structure_json(self):
        """测试构建结构JSON."""
        strategy = SimpleTruncationStrategy(max_files=3)

        # 创建测试文件
        class MockFile:
            def __init__(self, path, name, suffix, file_type):
                self.path = path
                self.name = name
                self.suffix = suffix
                self.file_type = file_type

        files = [
            MockFile("src/auth.py", "auth.py", "py", "code"),
            MockFile("src/main.py", "main.py", "py", "code"),
            MockFile("README.md", "README.md", "md", "doc"),  # 非代码文件
        ]

        file_summaries = {
            "file_test_src/auth.py": "Authentication module",
            "file_test_src/main.py": "Main entry point",
        }

        structure = strategy._build_structure_json(
            files, file_summaries, "test"
        )

        assert structure["repository"] == "test"
        assert len(structure["files"]) == 2  # 排除非代码文件
        assert structure["files"][0]["path"] == "src/auth.py"
        assert structure["files"][0]["summary"] == "Authentication module"

    def test_build_structure_json_truncation(self):
        """测试结构JSON截断."""
        strategy = SimpleTruncationStrategy(max_files=2)

        class MockFile:
            def __init__(self, path):
                self.path = path
                self.name = path.split("/")[-1]
                self.suffix = "py"
                self.file_type = "code"

        files = [MockFile(f"src/file_{i}.py") for i in range(5)]

        structure = strategy._build_structure_json(files, {}, "test")

        assert len(structure["files"]) == 2
        assert structure["note"] == "Truncated to 2 files"


class TestClusteringStrategy:
    """测试分层聚类策略."""

    def test_init_default(self):
        """测试默认初始化."""
        strategy = ClusteringStrategy()

        assert strategy.max_cluster_size == 80
        assert strategy.max_concurrency == 5
        assert strategy.merge_similarity_threshold == 0.7

    def test_init_custom(self):
        """测试自定义初始化."""
        strategy = ClusteringStrategy(
            max_cluster_size=100,
            max_concurrency=10,
            merge_similarity_threshold=0.8,
        )

        assert strategy.max_cluster_size == 100
        assert strategy.max_concurrency == 10
        assert strategy.merge_similarity_threshold == 0.8

    def test_validate_config_valid(self):
        """测试有效配置验证."""
        strategy = ClusteringStrategy()

        assert strategy.validate_config()

    def test_validate_config_invalid(self):
        """测试无效配置验证."""
        strategy = ClusteringStrategy(
            max_cluster_size=10,  # 小于20
            max_concurrency=0,  # 无效
            merge_similarity_threshold=1.5,  # 超出范围
        )

        assert not strategy.validate_config()

    def test_get_directory_prefix(self):
        """测试获取目录前缀."""
        strategy = ClusteringStrategy()

        assert strategy._get_directory_prefix("src/auth/login.py") == "src/auth"
        assert strategy._get_directory_prefix("main.py") == ""
        assert strategy._get_directory_prefix("a/b/c/d.py") == "a/b"

    def test_cluster_files_with_dependencies_empty(self):
        """测试空文件聚类."""
        strategy = ClusteringStrategy()

        clusters = strategy._cluster_files_with_dependencies([], [], 80)

        assert clusters == []

    def test_cluster_files_with_dependencies_single_group(self):
        """测试单组聚类."""
        strategy = ClusteringStrategy()

        files = [
            {"id": "file_1", "path": "src/auth.py"},
            {"id": "file_2", "path": "src/main.py"},
        ]

        clusters = strategy._cluster_files_with_dependencies(files, [], 80)

        assert len(clusters) == 1
        assert clusters[0].file_count == 2

    def test_directory_similarity(self):
        """测试目录相似度计算."""
        strategy = ClusteringStrategy()

        assert strategy._directory_similarity("src/auth", "src/auth") == 1.0
        assert strategy._directory_similarity("src/auth", "src/api") == 0.5
        assert strategy._directory_similarity("a/b/c", "a/b/d") == 2 / 3

    def test_string_similarity(self):
        """测试字符串相似度计算."""
        strategy = ClusteringStrategy()

        assert strategy._string_similarity("hello world", "hello world") == 1.0
        assert strategy._string_similarity("hello", "world") == 0.0

        # 部分相似
        sim = strategy._string_similarity("user authentication", "user login")
        assert 0 < sim < 1

    def test_calculate_module_similarity(self):
        """测试模块相似度计算."""
        strategy = ClusteringStrategy()

        m1 = ModuleInfo(
            name="User Authentication",
            description="Handle user login",
            files=["file_1", "file_2"],
        )
        m2 = ModuleInfo(
            name="User Login",
            description="User authentication system",
            files=["file_2", "file_3"],
        )

        sim = strategy._calculate_module_similarity(m1, m2)

        assert 0 <= sim <= 1
        # 有共同文件，相似度应该较高
        assert sim > 0

    def test_fallback_module_detection(self):
        """测试降级模块检测."""
        strategy = ClusteringStrategy()

        cluster = FileCluster(
            id="test_cluster",
            file_ids=["file_1", "file_2"],
            directory_prefix="src/auth",
        )

        result = strategy._fallback_module_detection(cluster)

        assert result.cluster_id == "test_cluster"
        assert len(result.modules) == 1
        assert "src/auth" in result.modules[0].name
        assert result.metadata["fallback"]


class TestFileCluster:
    """测试FileCluster数据类."""

    def test_basic_properties(self):
        """测试基本属性."""
        cluster = FileCluster(
            id="test",
            file_ids=["f1", "f2", "f3"],
            internal_edges=[("f1", "f2", 1)],
            external_edges=[("f1", "f3", 1)],
        )

        assert cluster.file_count == 3
        assert cluster.internal_dependency_count == 1
        assert cluster.external_dependency_count == 1

    def test_empty_id_raises(self):
        """测试空ID抛出异常."""
        with pytest.raises(ValueError):
            FileCluster(id="")


class TestMergedModule:
    """测试MergedModule数据类."""

    def test_basic_properties(self):
        """测试基本属性."""
        module = MergedModule(
            id="test_module",
            name="Test Module",
            file_ids=["f1", "f2"],
            source_clusters=["c1", "c2"],
        )

        assert module.file_count == 2
        assert len(module.source_clusters) == 2

    def test_empty_id_raises(self):
        """测试空ID抛出异常."""
        with pytest.raises(ValueError):
            MergedModule(id="", name="test")


class TestModuleDetectionResult:
    """测试ModuleDetectionResult数据类."""

    def test_default_values(self):
        """测试默认值."""
        result = ModuleDetectionResult()

        assert result.module_ids == []
        assert result.workflow_ids == []
        assert result.metadata == {}

    def test_custom_values(self):
        """测试自定义值."""
        result = ModuleDetectionResult(
            module_ids=["m1", "m2"],
            workflow_ids=["w1"],
            metadata={"strategy": "test"},
        )

        assert result.module_ids == ["m1", "m2"]
        assert result.workflow_ids == ["w1"]
        assert result.metadata["strategy"] == "test"
