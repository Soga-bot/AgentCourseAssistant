"""
工具管理器 - 注册、管理和执行工具

工具(Tool)是Agent可以调用的函数或方法。
ToolManager负责工具的注册、查找和执行。

架构说明：
    ToolManager 是 Agent 与外部能力的桥梁。
    调用链路：Agent 通过 call_tool() → ToolManager.call() → 实际工具函数 执行操作。

    工具注册方式：
    1. 直接注册 Tool 实例：调用 manager.register(tool)，需手动构造 Tool 对象。
    2. 通过 register_from_function 从函数自动推断参数：调用 manager.register_from_function(func)，
       利用 inspect.signature 自动提取函数签名、参数类型等信息，无需手动描述参数。
"""
from typing import Dict, Callable, Any, Optional, List
import logging
import inspect
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """工具定义

    封装一个可被Agent调用的函数
    """
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any]
    return_type: str = "any"

    def to_json_schema(self) -> Dict:
        """
        转换为JSON Schema格式

        用于将工具信息传递给LLM，让LLM了解如何调用工具

        Returns:
            JSON Schema格式的工具描述
        """
        # WHY: LLM需要知道工具的参数格式才能正确生成调用代码。
        #      JSON Schema 是描述 JSON 数据结构的标准格式，LLM 可以据此理解
        #      每个参数的名称、类型、是否必填，从而生成合规的工具调用参数。
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters,
                # 默认所有参数均为必填，简化 LLM 的调用决策
                "required": list(self.parameters.keys())
            }
        }

    def __repr__(self) -> str:
        return f"<Tool {self.name}>"


class ToolManager:
    """
    工具管理器

    负责：
    - 工具的注册
    - 工具的查找
    - 工具的执行
    - 生成工具的JSON Schema（用于LLM）

    使用示例：
        manager = ToolManager()

        # 注册工具
        manager.register_from_function(
            my_function,
            name="my_tool",
            description="My tool description"
        )

        # 执行工具
        result = await manager.call("my_tool", param1="value1")
    """

    def __init__(self):
        """初始化工具管理器"""
        self._tools: Dict[str, Tool] = {}
        logger.info("[ToolManager] Initialized")

    def register(self, tool: Tool):
        """
        注册工具

        Args:
            tool: Tool实例
        """
        if tool.name in self._tools:
            logger.warning(f"[ToolManager] Tool '{tool.name}' already registered, overwriting")

        self._tools[tool.name] = tool
        logger.info(f"[ToolManager] Tool registered: {tool.name}")

    def register_from_function(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None
    ):
        """
        从函数注册工具

        自动从函数签名推断参数信息

        Args:
            func: 要注册的函数
            name: 工具名称（默认使用函数名）
            description: 工具描述（默认使用函数docstring）
        """
        # 工具名称优先使用调用者显式指定的 name，否则回退到函数原始名称
        func_name = name or func.__name__
        # 工具描述优先使用调用者显式指定的 description，否则回退到函数 docstring，最后使用默认值
        func_desc = description or func.__doc__ or f"Tool: {func_name}"

        # WHY: 利用 inspect.signature 自动推断参数信息，避免调用者手动描述每个参数，
        #      降低注册成本，也保证参数描述与函数定义始终一致。
        sig = inspect.signature(func)
        parameters = {}

        for param_name, param in sig.parameters.items():
            # 跳过 self 参数——当注册的是实例方法时，self 由 Python 自动绑定，
            # 不应作为工具参数暴露给 LLM
            if param_name == 'self':
                continue

            # 获取参数类型注解；若函数未标注类型，默认视为 string（最宽松的类型）
            param_type = param.annotation if param.annotation != inspect.Parameter.empty else "string"
            param_desc = f"Parameter: {param_name}"

            # WHY: 将 Python 类型注解（如 str, int, List[str]）转换为 JSON Schema 类型
            #      （如 "string", "integer", "array"），以便 LLM 生成符合类型的参数值。
            json_type = self._get_json_type(param_type)

            parameters[param_name] = {
                "type": json_type,
                "description": param_desc
            }

        tool = Tool(
            name=func_name,
            description=func_desc,
            func=func,
            parameters=parameters
        )

        self.register(tool)

    def get_tool(self, name: str) -> Optional[Tool]:
        """
        获取工具

        Args:
            name: 工具名称

        Returns:
            Tool实例，如果不存在则返回None
        """
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """
        列出所有工具

        Returns:
            Tool列表
        """
        return list(self._tools.values())

    def get_tools_json_schema(self) -> List[Dict]:
        """
        获取所有工具的JSON Schema

        用于传递给LLM，让LLM了解有哪些工具可用

        Returns:
            JSON Schema列表
        """
        return [tool.to_json_schema() for tool in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        """
        检查工具是否存在

        Args:
            name: 工具名称

        Returns:
            如果工具存在返回True，否则返回False
        """
        return name in self._tools

    async def call(self, name: str, **kwargs) -> Any:
        """
        执行工具

        Args:
            name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 如果工具不存在
        """
        tool = self.get_tool(name)

        if not tool:
            # WHY: 当工具不存在时，不仅报告错误，还列出所有可用工具名称，
            #      帮助调用者快速定位是名称拼写错误还是工具未注册，降低调试成本。
            available_tools = list(self._tools.keys())
            raise ValueError(
                f"Tool not found: {name}. "
                f"Available tools: {available_tools}"
            )

        logger.info(f"[ToolManager] Calling tool: {name} with params: {list(kwargs.keys())}")

        try:
            # WHY: 工具函数可能是同步或异步的，需要统一处理。
            #      使用 inspect.iscoroutinefunction 在运行时检测函数类型：
            #      - 异步函数（async def）：使用 await 等待结果
            #      - 同步函数（普通 def）：直接调用获取结果
            #      这样 ToolManager.call() 无论面对哪种函数，对外都表现为统一的异步接口。
            if inspect.iscoroutinefunction(tool.func):
                result = await tool.func(**kwargs)
            else:
                result = tool.func(**kwargs)

            logger.info(f"[ToolManager] Tool '{name}' executed successfully")
            return result

        except Exception as e:
            logger.error(f"[ToolManager] Tool '{name}' failed: {e}")
            raise

    def _get_json_type(self, python_type) -> str:
        """
        将Python类型转换为JSON类型

        Args:
            python_type: Python类型

        Returns:
            JSON类型字符串
        """
        # WHY: Python 类型与 JSON Schema 类型并非一一对应，需要建立映射关系。
        #      例如 Python 的 list 对应 JSON 的 array，dict 对应 object，
        #      float 对应 number（JSON 中没有整数/浮点数的区分，但 Schema 可以细分）。
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object"
        }

        # 第一层：直接匹配基础类型（如 str, int, bool）
        if python_type in type_map:
            return type_map[python_type]

        # 第二层：处理泛型类型（如 List[str], Dict[str, int], Optional[str]）
        # WHY: typing 模块的泛型在运行时是 _GenericAlias 实例，不会直接命中 type_map。
        #      通过 __origin__ 属性可以获取其底层容器类型（List[str].__origin__ → list），
        #      再将容器类型映射到对应的 JSON 类型即可。
        if hasattr(python_type, "__origin__"):
            origin = python_type.__origin__
            if origin in type_map:
                return type_map[origin]

        # 第三层：无法识别的类型统一回退为 "string"，保证不会因未知类型导致注册失败
        return "string"

    def __repr__(self) -> str:
        return f"<ToolManager tools={len(self._tools)}>"


# ==================== 便捷函数 ====================

def create_tool_from_function(
    func: Callable,
    name: Optional[str] = None,
    description: Optional[str] = None
) -> Tool:
    """
    从函数创建Tool实例

    Args:
        func: 函数
        name: 工具名称
        description: 工具描述

    Returns:
        Tool实例
    """
    manager = ToolManager()
    manager.register_from_function(func, name, description)
    return manager.get_tool(name or func.__name__)
