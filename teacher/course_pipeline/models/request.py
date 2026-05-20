"""课程生成请求模型

定义课程生成请求的数据结构
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CourseGenerateRequest:
    """课程生成请求

    Attributes:
        version: 教材版本 (如: "renjiao_v1")
        grade: 年级 (如: "七年级上册")
        chapter_id: 章节ID (如: "c1_youshu")
        student_level: 学情配置
            - 基础薄弱: 概念拆解到最细，计算步骤一步不跳
            - 中等巩固: 概念讲透，加易混点辨析
            - 培优拓展: 概念延伸拓展，加一题多解
        purpose: 用途类型
            - 学生自学
            - 教师备课教案
            - 复习串讲
            - 习题课
        content_type: 内容类型（教师专用模式）
            - lesson_plan: 教师备课教案
            - teaching_script: 课堂讲解逐字稿
            - board_design: 板书设计
            - review_outline: 复习串讲大纲
        custom_topic: 自定义专题名称
        custom_outline: 自定义大纲内容（教师提供的课程大纲/手稿）
    """
    version: str                    # 教材版本
    grade: str                      # 年级
    chapter_id: str                 # 章节ID
    student_level: str              # 学情
    purpose: str                    # 用途
    content_type: Optional[str] = None  # 内容类型
    custom_topic: Optional[str] = None  # 自定义专题名称
    custom_outline: Optional[str] = None  # 自定义大纲内容
