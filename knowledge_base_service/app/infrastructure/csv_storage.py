"""CSV存储模块 - 用于存储仓库初始化状态."""

import csv
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# CSV文件路径
DATA_DIR = Path(__file__).parent.parent.parent / "data"
REPO_STATUS_CSV = DATA_DIR / "repo_initialization.csv"

# CSV表头
CSV_HEADERS = ["repo_id", "initial_status", "repo_name", "repo_path"]


class InitializationStatus:
    """初始化状态常量."""

    PENDING = "Pending"
    COMPLETED = "Completed"
    FAILED = "Failed"


@dataclass
class RepoInitializationRecord:
    """仓库初始化记录."""

    repo_id: str
    initial_status: str
    repo_name: str
    repo_path: str

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "repo_id": self.repo_id,
            "initial_status": self.initial_status,
            "repo_name": self.repo_name,
            "repo_path": self.repo_path,
        }


class RepoStatusStorage:
    """仓库状态存储类."""

    def __init__(self, csv_path: Optional[Path] = None):
        """初始化存储.

        Args:
            csv_path: CSV文件路径，默认为项目data目录下的repo_initialization.csv
        """
        self.csv_path = csv_path or REPO_STATUS_CSV
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """确保CSV文件和目录存在."""
        # 确保目录存在
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        # 如果文件不存在，创建并写入表头
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                writer.writeheader()
            logger.info(f"Created repo status CSV file: {self.csv_path}")

    def create_record(
        self,
        repo_id: str,
        repo_name: str,
        repo_path: str,
        status: str = InitializationStatus.PENDING,
    ) -> RepoInitializationRecord:
        """创建新记录.

        Args:
            repo_id: 仓库ID
            repo_name: 仓库名称
            repo_path: 仓库路径
            status: 初始状态，默认为Pending

        Returns:
            创建的记录
        """
        self._ensure_file_exists()

        # 检查是否已存在记录
        existing = self.get_record(repo_id)
        if existing:
            logger.warning(f"Record for repo {repo_id} already exists, updating instead")
            return self.update_status(repo_id, status) or existing

        record = RepoInitializationRecord(
            repo_id=repo_id,
            initial_status=status,
            repo_name=repo_name,
            repo_path=repo_path,
        )

        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writerow(record.to_dict())

        logger.info(f"Created repo status record: {repo_id} - {status}")
        return record

    def get_record(self, repo_id: str) -> Optional[RepoInitializationRecord]:
        """根据repo_id获取记录.

        Args:
            repo_id: 仓库ID

        Returns:
            记录或None（如果不存在）
        """
        if not self.csv_path.exists():
            return None

        try:
            with open(self.csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["repo_id"] == repo_id:
                        return RepoInitializationRecord(
                            repo_id=row["repo_id"],
                            initial_status=row["initial_status"],
                            repo_name=row["repo_name"],
                            repo_path=row["repo_path"],
                        )
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")

        return None

    def update_status(self, repo_id: str, status: str) -> Optional[RepoInitializationRecord]:
        """更新记录状态.

        Args:
            repo_id: 仓库ID
            status: 新状态

        Returns:
            更新后的记录或None（如果不存在）
        """
        if not self.csv_path.exists():
            return None

        records = []
        target_record = None

        # 读取所有记录
        with open(self.csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["repo_id"] == repo_id:
                    row["initial_status"] = status
                    target_record = RepoInitializationRecord(
                        repo_id=row["repo_id"],
                        initial_status=row["initial_status"],
                        repo_name=row["repo_name"],
                        repo_path=row["repo_path"],
                    )
                records.append(row)

        if target_record is None:
            logger.warning(f"Record for repo {repo_id} not found for update")
            return None

        # 写回文件
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
            writer.writerows(records)

        logger.info(f"Updated repo status: {repo_id} - {status}")
        return target_record

    def get_all_records(self) -> list[RepoInitializationRecord]:
        """获取所有记录.

        Returns:
            所有记录的列表
        """
        records = []

        if not self.csv_path.exists():
            return records

        try:
            with open(self.csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(
                        RepoInitializationRecord(
                            repo_id=row["repo_id"],
                            initial_status=row["initial_status"],
                            repo_name=row["repo_name"],
                            repo_path=row["repo_path"],
                        )
                    )
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")

        return records


# 全局存储实例
_storage_instance: Optional[RepoStatusStorage] = None


def get_repo_status_storage() -> RepoStatusStorage:
    """获取仓库状态存储实例."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = RepoStatusStorage()
    return _storage_instance
