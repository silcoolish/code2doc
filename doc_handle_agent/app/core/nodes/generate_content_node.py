"""生成内容节点."""

from app.core.content_generator import ContentGenerator
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GenerateContentNode(WorkflowNode):
    """生成内容节点."""

    def __init__(self, content_generator: ContentGenerator):
        self.content_generator = content_generator

    @property
    def name(self) -> str:
        return "generate_content"

    async def execute(self, state: AgentState) -> AgentState:
        """生成内容."""
        idx = state["current_paragraph_index"]
        total = state["total_paragraphs"]

        if idx >= total:
            return state

        paragraph = state["paragraphs"][idx]

        logger.info(
            "workflow_node",
            node=self.name,
            current=idx + 1,
            total=total,
            paragraph_id=paragraph.id,
            is_list=paragraph.is_list,
            has_img=bool(paragraph.img),
        )

        try:
            state["status"] = GenerationStatus.GENERATING.value

            if paragraph.is_list:
                state["message"] = f"正在生成第{idx + 1}/{total}个段落列表: {paragraph.prompt[:30] if paragraph.prompt else ''}..."
            else:
                state["message"] = f"正在生成第{idx + 1}/{total}个段落: {paragraph.prompt[:30] if paragraph.prompt else ''}..."

            # generate 方法返回 List[GeneratedContentResult]
            results = await self.content_generator.generate(
                paragraph=paragraph,
                repo_id=state["repo_id"],
            )

            # 保存生成的内容列表
            state["generated_contents"][paragraph.id] = results

            # 收集并保存图片信息
            images = []
            for result in results:
                images.extend(result.images)
                # 递归收集子段落的图片
                images.extend(self._collect_images_recursive(result.children))

            if images:
                state["generated_images"][paragraph.id] = images

            state["current_paragraph_index"] = idx + 1

            # 记录生成结果
            if paragraph.is_list:
                logger.info(
                    "generate_content_success",
                    paragraph_id=paragraph.id,
                    is_list=True,
                    result_count=len(results),
                    has_children=len(paragraph.children) > 0,
                    total_image_count=len(images),
                )
            else:
                result = results[0] if results else None
                logger.info(
                    "generate_content_success",
                    paragraph_id=paragraph.id,
                    is_list=False,
                    is_heading=result.is_heading if result else None,
                    content_length=len(result.content) if result else 0,
                    image_count=len(result.images) if result else 0,
                )

        except Exception as e:
            logger.error(
                "generate_content_failed",
                paragraph_id=paragraph.id,
                error=str(e),
            )
            # 出错时保存一个空结果
            from app.core.state import GeneratedContentResult
            state["generated_contents"][paragraph.id] = [
                GeneratedContentResult(
                    is_heading=paragraph.is_heading,
                    content=f"[生成失败: {str(e)}]",
                    children=[],
                    images=[],
                )
            ]
            state["current_paragraph_index"] = idx + 1

        return state

    def _collect_images_recursive(self, results: list) -> list:
        """递归收集所有子段落的图片."""
        images = []
        for result in results:
            images.extend(result.images)
            if result.children:
                images.extend(self._collect_images_recursive(result.children))
        return images
