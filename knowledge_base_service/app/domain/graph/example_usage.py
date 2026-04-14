"""GraphHelper 使用示例.

此文件展示了如何在流水线阶段中使用 GraphHelper 类来操作图节点。
"""

import asyncio
from datetime import datetime
from typing import List

from app.domain.graph import (
    GraphHelper,
    Repository,
    Directory,
    File,
    Class,
    Method,
    Module,
    Workflow,
)
from app.infrastructure.db import get_graph_db_client


async def example_structure_graph_build():
    """结构图构建阶段使用示例.

    展示了如何使用 GraphHelper 来创建仓库结构节点。
    """
    # 获取图数据库客户端
    graph_db = get_graph_db_client()

    # 创建 GraphHelper 实例
    helper = GraphHelper(graph_db)

    repo_id = "repo_myproject"
    repo_name = "myproject"
    repo_path = "/path/to/repo"

    # 1. 创建 Repository 节点
    repository = Repository(
        id=f"repo_{repo_name}",
        name=repo_name,
        path=repo_path,
        repo_id=repo_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await helper.create_repository(repository)

    # 2. 创建 Directory 节点
    directory = Directory(
        id=f"dir_{repo_name}_src",
        name="src",
        path="src",
        repo_id=repo_id,
    )
    await helper.create_directory(directory, parent_id=repository.id)

    # 3. 创建 File 节点（会自动读取文件内容）
    file_node = File(
        id=f"file_{repo_name}_src/main.py",
        name="main.py",
        path="src/main.py",
        file_type="code",
        suffix=".py",
        repo_id=repo_id,
    )
    await helper.create_file(file_node, parent_id=directory.id, repo_path=repo_path)

    # 4. 创建 Class 节点
    class_node = Class(
        id=f"class_{repo_name}_src/main.py_MainClass",
        name="MainClass",
        file_path="src/main.py",
        start_line=10,
        end_line=50,
        language="python",
        code="class MainClass: ...",
        docstring="主类",
        real_type="Class",
        repo_id=repo_id,
    )
    await helper.create_class(class_node, file_id=file_node.id)

    # 5. 创建 Method 节点
    method_node = Method(
        id=f"method_{repo_name}_src/main.py_MainClass_init",
        name="__init__",
        file_path="src/main.py",
        start_line=15,
        end_line=20,
        language="python",
        code="def __init__(self): ...",
        docstring="构造函数",
        class_id=class_node.id,
        repo_id=repo_id,
    )
    await helper.create_method(method_node, parent_id=class_node.id)

    print("结构图构建完成!")


async def example_module_detection():
    """模块检测阶段使用示例.

    展示了如何使用 GraphHelper 来创建模块和工作流节点。
    """
    graph_db = get_graph_db_client()
    helper = GraphHelper(graph_db)

    repo_id = "repo_myproject"

    # 1. 创建 Module 节点
    module = Module(
        id=f"module_{repo_id}_auth",
        name="认证模块",
        summary="处理用户认证和授权功能",
        detail="包含登录、注册、Token刷新等功能",
        keywords=["auth", "login", "jwt"],
        confidence=0.95,
        repo_id=repo_id,
    )
    await helper.create_module(module)

    # 2. 创建 Workflow 节点
    workflow = Workflow(
        id=f"workflow_{repo_id}_login",
        name="用户登录流程",
        summary="用户登录的完整流程",
        detail="1. 验证用户名密码 -> 2. 生成JWT -> 3. 返回Token",
        keywords=["login", "auth", "jwt"],
        confidence=0.92,
        module_id=module.id,
        repo_id=repo_id,
    )
    await helper.create_workflow(workflow)

    # 3. 创建 BELONG_TO 关系
    await helper.create_belong_to_relationship(
        from_id=workflow.id,
        to_id=module.id,
        from_label="Workflow",
    )

    # 4. 假设 file_1 属于这个模块
    await helper.create_belong_to_relationship(
        from_id=f"file_{repo_id}_src/auth.py",
        to_id=module.id,
        from_label="File",
    )

    print("模块检测完成!")


async def example_queries():
    """查询操作示例.

    展示了如何使用 GraphHelper 来查询节点。
    """
    graph_db = get_graph_db_client()
    helper = GraphHelper(graph_db)

    repo_id = "repo_myproject"

    # 1. 获取仓库下所有文件
    files = await helper.get_files_by_repo(repo_id)
    print(f"仓库 {repo_id} 有 {len(files)} 个文件")

    # 2. 获取仓库下所有类
    classes = await helper.get_classes_by_repo(repo_id)
    print(f"仓库 {repo_id} 有 {len(classes)} 个类")

    # 3. 获取仓库下所有方法
    methods = await helper.get_methods_by_repo(repo_id)
    print(f"仓库 {repo_id} 有 {len(methods)} 个方法")

    # 4. 获取仓库下所有模块
    modules = await helper.get_modules_by_repo(repo_id)
    print(f"仓库 {repo_id} 有 {len(modules)} 个模块")

    # 5. 根据路径获取文件
    file_node = await helper.get_file_by_path(repo_id, "src/main.py")
    if file_node:
        print(f"找到文件: {file_node['name']}")

    # 6. 根据ID获取节点
    class_node = await helper.get_class_by_id(f"class_{repo_id}_src/main.py_MainClass")
    if class_node:
        print(f"找到类: {class_node}")


async def example_batch_operations():
    """批量操作示例.

    展示了如何使用 GraphHelper 进行批量操作。
    """
    graph_db = get_graph_db_client()
    helper = GraphHelper(graph_db)

    repo_id = "repo_myproject"

    # 1. 批量更新节点摘要
    updates: List[tuple] = [
        (f"file_{repo_id}_src/main.py", "主程序文件"),
        (f"file_{repo_id}_src/utils.py", "工具函数文件"),
    ]
    updated = await helper.update_node_summaries_batch("File", updates)
    print(f"更新了 {updated} 个文件的摘要")

    # 2. 批量更新 embedding ID
    embedding_updates: List[tuple] = [
        (f"file_{repo_id}_src/main.py", "emb_001"),
        (f"file_{repo_id}_src/utils.py", "emb_002"),
    ]
    updated = await helper.update_node_embedding_ids_batch("File", embedding_updates)
    print(f"更新了 {updated} 个文件的 embedding ID")


# 如果直接运行此文件，执行示例
if __name__ == "__main__":
    print("=" * 50)
    print("GraphHelper 使用示例")
    print("=" * 50)

    # 注意：运行这些示例需要连接到 Neo4j 数据库
    # asyncio.run(example_structure_graph_build())
    # asyncio.run(example_module_detection())
    # asyncio.run(example_queries())
    # asyncio.run(example_batch_operations())

    print("\n示例代码已准备就绪，取消注释上面的函数调用来运行。")
    print("请确保已启动 Neo4j 服务。")
