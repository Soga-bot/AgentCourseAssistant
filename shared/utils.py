"""
公共工具函数

提供各种实用工具函数：
- JSON处理
- 字符串处理
- 文件处理
- 时间处理
"""

import json
import re
import os
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
from datetime import datetime
import hashlib


# ==================== JSON处理 ====================

def sanitize_json_output(text: str) -> str:
    """
    清理LLM输出的JSON，去除markdown标记等

    Args:
        text: 原始文本

    Returns:
        清理后的JSON字符串

    示例：
        输入: ```json\n{"key": "value"}\n```
        输出: {"key": "value"}
    """
    # 去除markdown代码块标记
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)

    # 去除多余的空白
    text = text.strip()

    # 改进的JSON提取逻辑：找到匹配的 {}
    stack = []
    json_start = -1
    json_end = -1

    for i, char in enumerate(text):
        if char == '{':
            if not stack:  # 第一个 {
                json_start = i
            stack.append(i)
        elif char == '}':
            if stack:
                stack.pop()
                if not stack:  # 匹配的最后一个 }
                    json_end = i
                    break

    if json_start >= 0 and json_end > json_start:
        return text[json_start:json_end + 1]

    # 如果没有找到匹配的 {}，尝试简单的查找
    simple_start = text.find('{')
    simple_end = text.rfind('}')
    if simple_start >= 0 and simple_end > simple_start:
        return text[simple_start:simple_end + 1]

    return text


def extract_json(text: str) -> Optional[Dict]:
    """
    从文本中提取JSON对象 - 使用多重策略确保解析成功

    Args:
        text: 包含JSON的文本

    Returns:
        解析后的字典，失败返回None
    """
    if not text or not text.strip():
        return None

    cleaned = sanitize_json_output(text)

    # 预处理：修复LLM输出中LaTeX反斜杠未正确转义的问题
    # 必须在json.loads()之前执行，否则 \times 中的 \t 会被解释为tab
    cleaned = fix_latex_backslashes(cleaned)

    # 策略1：直接解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 策略2：使用json_repair库（最可靠）
    try:
        import json_repair
        repaired = json_repair.repair_json(cleaned, skip_json_loads=False)
        return json.loads(repaired)
    except ImportError:
        pass
    except Exception:
        pass

    # 记录最终失败
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"JSON解析最终失败，前200字符: {cleaned[:200]}")

    return None


def fix_latex_backslashes(text: str) -> str:
    """
    修复JSON字符串值内的LaTeX反斜杠

    LLM可能在JSON字符串值中使用单个反斜杠书写LaTeX命令（如 \\times），
    但JSON规范要求反斜杠必须双写（如 \\\\times）。
    直接 json.loads() 会将 \\t 解释为 tab，导致 \\times 变成 乘号错误。

    此函数在 json.loads() 之前运行，将JSON字符串值内属于LaTeX命令的
    单反斜杠双写。通过判断反斜杠后面是否跟连续小写字母来区分
    LaTeX命令和合法JSON转义序列（\\n \\t \\\" 等）。
    """

    def replace_in_string(match):
        """在JSON字符串值内将LaTeX命令的单反斜杠双写"""
        content = match.group(0)
        # 策略：将 \后跟2个以上小写字母的模式中的 \ 双写
        # LaTeX命令: \times, \frac, \begin, \left, \right, \boxed ...
        # 合法JSON转义: \n, \t, \", \\, \/ (后跟单字符，不是连续小写字母)
        def double_backslash(m):
            return '\\\\' + m.group(1)
        result = re.sub(r'(?<!\\)\\([a-z]{2,})', double_backslash, content)
        return result

    # 使用正则表达式处理所有JSON字符串值
    pattern = r'"(?:[^"\\]|\\.)*"'
    return re.sub(pattern, replace_in_string, text)


def parse_json_with_fallback(text: str, fallback: Any = None) -> Any:
    """
    解析JSON，失败时返回fallback值

    Args:
        text: JSON字符串
        fallback: 解析失败时的返回值

    Returns:
        解析后的对象或fallback值
    """
    result = extract_json(text)
    return result if result is not None else fallback


# ==================== 字符串处理 ====================

def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    截断文本到指定长度

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后的后缀

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def clean_whitespace(text: str) -> str:
    """
    清理多余的空白字符

    Args:
        text: 原始文本

    Returns:
        清理后的文本
    """
    # 替换多个空白为单个空格
    text = re.sub(r'\s+', ' ', text)
    # 去除首尾空白
    return text.strip()


def split_into_chunks(text: str, chunk_size: int = 1000) -> List[str]:
    """
    将文本分割成指定大小的块

    Args:
        text: 原始文本
        chunk_size: 每块的大小

    Returns:
        文本块列表
    """
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])
    return chunks


def escape_latex(text: str) -> str:
    """
    转义LaTeX特殊字符

    Args:
        text: 原始文本

    Returns:
        转义后的文本
    """
    latex_special_chars = {
        '\\': r'\textbackslash{}',
        '{': r'\{',
        '}': r'\}',
        '$': r'\$',
        '&': r'\&',
        '#': r'\#',
        '^': r'\^{}',
        '_': r'\_',
        '~': r'\textasciitilde{}',
        '%': r'\%',
    }

    for char, escaped in latex_special_chars.items():
        text = text.replace(char, escaped)

    return text


def unescape_latex(text: str) -> str:
    """
    反转义LaTeX特殊字符

    Args:
        text: 转义后的文本

    Returns:
        原始文本
    """
    # 按照转义的逆序进行替换
    latex_unescape_map = {
        r'\textbackslash{}': '\\',
        r'\{': '{',
        r'\}': '}',
        r'\$': '$',
        r'\&': '&',
        r'\#': '#',
        r'\^{}': '^',
        r'\_': '_',
        r'\textasciitilde{}': '~',
        r'\%': '%',
    }

    for escaped, char in latex_unescape_map.items():
        text = text.replace(escaped, char)

    return text


# ==================== 文件处理 ====================

def ensure_dir(path: Union[str, Path]) -> Path:
    """
    确保目录存在，不存在则创建

    Args:
        path: 目录路径

    Returns:
        Path对象
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_file(file_path: Union[str, Path], encoding: str = "utf-8") -> str:
    """
    读取文件内容

    Args:
        file_path: 文件路径
        encoding: 文件编码

    Returns:
        文件内容
    """
    return Path(file_path).read_text(encoding=encoding)


def write_file(
    file_path: Union[str, Path],
    content: str,
    encoding: str = "utf-8"
) -> None:
    """
    写入文件内容

    Args:
        file_path: 文件路径
        content: 文件内容
        encoding: 文件编码
    """
    ensure_dir(Path(file_path).parent)
    Path(file_path).write_text(content, encoding=encoding)


def read_json(file_path: Union[str, Path]) -> Dict:
    """
    读取JSON文件

    Args:
        file_path: JSON文件路径

    Returns:
        解析后的字典
    """
    return json.loads(read_file(file_path))


def write_json(
    file_path: Union[str, Path],
    data: Dict,
    indent: int = 2,
    ensure_ascii: bool = False
) -> None:
    """
    写入JSON文件

    Args:
        file_path: JSON文件路径
        data: 要写入的数据
        indent: 缩进空格数
        ensure_ascii: 是否确保ASCII编码
    """
    content = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    write_file(file_path, content)


def get_file_hash(file_path: Union[str, Path]) -> str:
    """
    计算文件的MD5哈希值

    Args:
        file_path: 文件路径

    Returns:
        MD5哈希值
    """
    content = read_file(file_path)
    return hashlib.md5(content.encode()).hexdigest()


# ==================== 时间处理 ====================

def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    获取当前时间的字符串表示

    Args:
        fmt: 时间格式

    Returns:
        时间字符串
    """
    return datetime.now().strftime(fmt)


def now_iso() -> str:
    """获取ISO格式的当前时间"""
    return datetime.now().isoformat()


def parse_time(time_str: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """
    解析时间字符串

    Args:
        time_str: 时间字符串
        fmt: 时间格式

    Returns:
        datetime对象
    """
    return datetime.strptime(time_str, fmt)


def format_duration(seconds: float) -> str:
    """
    格式化时长

    Args:
        seconds: 秒数

    Returns:
        格式化的时长字符串 (如: "1分30秒")
    """
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}分{secs:.0f}秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}小时{minutes}分"


# ==================== 其他工具 ====================

def generate_id(prefix: str = "") -> str:
    """
    生成唯一ID

    Args:
        prefix: ID前缀

    Returns:
        唯一ID字符串
    """
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    return f"{prefix}{unique_id}" if prefix else unique_id


def merge_dicts(*dicts: Dict) -> Dict:
    """
    合并多个字典

    Args:
        *dicts: 要合并的字典

    Returns:
        合并后的字典
    """
    result = {}
    for d in dicts:
        result.update(d)
    return result


def deep_get(obj: Dict, keys: str, default: Any = None) -> Any:
    """
    深度获取字典值

    Args:
        obj: 字典对象
        keys: 点分隔的键路径 (如: "a.b.c")
        default: 默认值

    Returns:
        获取的值或默认值
    """
    keys_list = keys.split('.')
    current = obj

    for key in keys_list:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default

    return current


def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """
    将列表分块

    Args:
        lst: 原始列表
        chunk_size: 每块大小

    Returns:
        分块后的列表
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def flatten_list(nested_list: List) -> List:
    """
    展平嵌套列表

    Args:
        nested_list: 嵌套列表

    Returns:
        展平后的列表
    """
    result = []
    for item in nested_list:
        if isinstance(item, list):
            result.extend(flatten_list(item))
        else:
            result.append(item)
    return result


# ==================== 进度条工具 ====================

class ProgressBar:
    """简单的进度条"""

    def __init__(self, total: int, width: int = 50):
        self.total = total
        self.width = width
        self.current = 0

    def update(self, n: int = 1):
        """更新进度"""
        self.current += n
        self._display()

    def _display(self):
        """显示进度条"""
        percent = self.current / self.total
        filled = int(self.width * percent)
        bar = '█' * filled + '░' * (self.width - filled)
        print(f'\r[{bar}] {percent:.1%} ({self.current}/{self.total})', end='', flush=True)

        if self.current >= self.total:
            print()  # 完成后换行



# ==================== 项目路径工具 ====================

def get_project_root():
    """获取项目根目录"""
    from pathlib import Path
    return Path(__file__).parent.parent


def get_course_output_dir(course_id: str):
    """
    获取课程输出目录

    Args:
        course_id: 课程ID

    Returns:
        Path对象
    """
    output_dir = get_project_root() / "output" / course_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir

