"""课程内容校验器

对 shared.validators.ContentValidator 的扩展和包装
添加课程生成特有的校验逻辑
"""

from shared.validators import ContentValidator as BaseContentValidator


class CourseContentValidator(BaseContentValidator):
    """
    课程内容校验器

    继承自 shared.validators.ContentValidator
    保留原有的所有校验功能，可在此添加课程生成特有的校验逻辑

    功能：
    - 公式格式校验（继承）
    - 超纲关键词检查（继承）
    - 结构完整性校验（继承）
    - 违规词检查（继承）
    - JSON格式校验（继承）
    - 课程生成特有的校验（可扩展）
    """

    pass
