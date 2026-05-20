"""
统一日志配置模块

所有日志文件将保存到 logs/ 目录，按日期和模块分类
"""
import os
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime


# 日志目录（使用项目根目录下的 logs 文件夹）
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 日志格式
DETAILED_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(funcName)-20s | %(lineno)-4d | %(message)s"
SIMPLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"

# 日期格式
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ColoredFormatter(logging.Formatter):
    """带颜色的控制台日志格式化器"""

    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
    }
    RESET = '\033[0m'

    def format(self, record):
        # 添加颜色
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    level: int = logging.INFO,
    console_level: int = logging.INFO,
    enable_console: bool = True,
    enable_file: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> None:
    """
    配置项目的统一日志系统

    日志文件结构：
    logs/
    ├── course_video_generator_YYYY-MM-DD.log      # 主流程日志
    ├── latex_generator_YYYY-MM-DD.log             # LaTeX生成日志
    ├── speech_generator_YYYY-MM-DD.log            # 语音生成日志
    ├── pdf_compiler_YYYY-MM-DD.log                # PDF编译日志
    ├── video_synthesizer_YYYY-MM-DD.log           # 视频合成日志
    ├── audio_utils_YYYY-MM-DD.log                 # 音频工具日志
    ├── errors_YYYY-MM-DD.log                      # 错误日志
    └── all_YYYY-MM-DD.log                         # 全局日志

    Args:
        level: 文件日志级别
        console_level: 控制台日志级别
        enable_console: 是否启用控制台输出
        enable_file: 是否启用文件输出
        max_bytes: 单个日志文件最大大小
        backup_count: 保留的备份文件数量
    """
    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # 设置最低级别，由handler控制

    # 清除现有的处理器
    root_logger.handlers.clear()

    # ========== 文件处理器 ==========

    if enable_file:
        today = datetime.now().strftime("%Y-%m-%d")

        # 1. 全局日志文件（所有日志）
        all_handler = RotatingFileHandler(
            LOG_DIR / f"all_{today}.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        all_handler.setLevel(level)
        all_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))
        root_logger.addHandler(all_handler)

        # 2. 错误日志文件（仅ERROR及以上）
        error_handler = RotatingFileHandler(
            LOG_DIR / f"errors_{today}.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))
        root_logger.addHandler(error_handler)

    # ========== 控制台处理器 ==========

    if enable_console:
        # Windows下不使用颜色（避免编码问题）
        if sys.platform == 'win32':
            console_formatter = logging.Formatter(CONSOLE_FORMAT, DATE_FORMAT)
        else:
            console_formatter = ColoredFormatter(CONSOLE_FORMAT, DATE_FORMAT)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)


def get_module_logger(module_name: str, log_filename: str = None) -> logging.Logger:
    """
    为特定模块创建专用的日志记录器

    每个模块的日志会同时写入：
    1. 全局日志文件 (all_YYYY-MM-DD.log)
    2. 模块专用日志文件 (module_name_YYYY-MM-DD.log)

    Args:
        module_name: 模块名称（通常使用 __name__）
        log_filename: 自定义日志文件名（不含扩展名）

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(module_name)
    logger.setLevel(logging.DEBUG)

    # 如果没有指定文件名，使用模块名
    if log_filename is None:
        # 将模块路径转换为文件名
        # 例如: teacher.video_pipeline.pipeline -> pipeline
        log_filename = module_name.split('.')[-1]

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{log_filename}_{today}.log"

    # 添加模块专用的文件处理器（如果还没有）
    # 检查是否已有同名的handler
    has_module_handler = any(
        isinstance(h, RotatingFileHandler) and
        log_file in h.baseFilename
        for h in logger.handlers
    )

    if not has_module_handler:
        module_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        module_handler.setLevel(logging.DEBUG)
        module_handler.setFormatter(logging.Formatter(DETAILED_FORMAT, DATE_FORMAT))
        logger.addHandler(module_handler)

    return logger


def cleanup_old_logs(days: int = 30) -> int:
    """
    清理超过指定天数的旧日志文件

    Args:
        days: 保留天数

    Returns:
        删除的文件数量
    """
    import time

    deleted_count = 0
    cutoff_time = time.time() - (days * 24 * 60 * 60)

    for log_file in LOG_DIR.glob("*.log*"):
        if log_file.stat().st_mtime < cutoff_time:
            try:
                log_file.unlink()
                deleted_count += 1
            except Exception as e:
                print(f"删除日志文件失败: {log_file}, 错误: {e}")

    return deleted_count


# 日志配置快捷方式
def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器的快捷方式

    使用方式：
        from video_pipeline.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("Hello, world!")
    """
    return get_module_logger(name)


# 默认日志级别
DEFAULT_LOG_LEVEL = logging.INFO

# 在模块导入时自动配置（可选）
# 取消注释以启用自动配置
# setup_logging()
