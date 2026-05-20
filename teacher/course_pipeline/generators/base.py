"""基础生成器接口

定义生成器的抽象基类
"""

from abc import ABC, abstractmethod
from typing import Optional, Callable
from ..models import CourseContent, CourseGenerateRequest


class BaseGenerator(ABC):
    """生成器基类

    所有生成器必须继承此类并实现 generate 方法
    """

    @abstractmethod
    async def generate(
        self,
        request: CourseGenerateRequest,
        progress_callback: Optional[Callable] = None
    ) -> CourseContent:
        """生成内容

        Args:
            request: 生成请求参数
            progress_callback: 进度回调函数，接收 (percent, message) 参数

        Returns:
            生成的课程内容

        Raises:
            ValueError: 参数错误
            Exception: 生成失败
        """
        pass

    def _update_progress(
        self,
        callback: Optional[Callable],
        percent: int,
        message: str
    ) -> None:
        """更新进度

        Args:
            callback: 进度回调函数
            percent: 进度百分比 (0-100)
            message: 进度消息
        """
        if callback:
            callback(percent, message)
