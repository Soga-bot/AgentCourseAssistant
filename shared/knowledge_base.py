"""
知识库单例模块

提供全局唯一的知识库实例，避免循环导入
"""

from course_pipeline.knowledge_base import KnowledgeBase

# 全局知识库实例
_knowledge_base = None


def get_knowledge_base() -> KnowledgeBase:
    """
    获取知识库实例（单例模式）

    Returns:
        KnowledgeBase: 知识库实例
    """
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = KnowledgeBase("./teacher/knowledge")
    return _knowledge_base


# 便捷访问
knowledge_base = get_knowledge_base()
