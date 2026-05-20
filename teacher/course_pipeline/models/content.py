"""课程内容模型

定义生成结果的数据结构
"""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class CourseContent:
    """课程内容

    Attributes:
        title: 课程标题
        grade: 年级
        chapter: 章节名称
        version: 教材版本
        student_level: 学情配置
        purpose: 用途类型
        sections: 课程各章节内容
            - 导入: 课程导入内容
            - 学习目标: 本章学习目标
            - 知识点详解: 核心知识点讲解
            - 典例精讲: 例题与解析
            - 易错点: 易错点提醒
            - 随堂小测: 练习题
            - 知识框架: 知识点框架
            - 课后拓展: 拓展内容
        diagrams: 图示信息（按章节组织的图示列表）
            格式: {"章节名": [{"type": "图示类型", "path": "图片路径", "spec": {...}}]}
        metadata: 元数据信息
            - generated_at: 生成时间
            - version: 教材版本
            - chapter_id: 章节ID
    """
    title: str
    grade: str
    chapter: str
    version: str
    student_level: str
    purpose: str
    sections: Dict[str, str]
    diagrams: Dict[str, list] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典格式

        Returns:
            包含所有课程信息的字典
        """
        return {
            "title": self.title,
            "grade": self.grade,
            "chapter": self.chapter,
            "version": self.version,
            "student_level": self.student_level,
            "purpose": self.purpose,
            "sections": self.sections,
            "diagrams": self.diagrams,
            "metadata": self.metadata,
        }
