"""
统一的LLM客户端

支持双模式系统共享的LLM调用功能：
- 豆包2.0 Pro 模型支持（主推）
- DeepSeek-V3 模型支持（备用）
- 自动重试机制
- 请求限流控制
- 响应缓存（可选）
- Token使用统计

请求处理流程：
  请求入口(call) → 缓存检查 → 并发控制(Semaphore) → 限流等待 → 构建请求体 → HTTP调用 → 解析响应 → 缓存写入
  失败时：指数退避等待 → 重试(最多max_retries次) → 全部失败返回错误
"""

import asyncio
import time
import os
import logging
import httpx
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """LLM提供商"""
    DOUBAO = "doubao"      # 当前主要使用：豆包2.0 Pro（doubao-seed-2-0-pro-260215）
    DEEPSEEK = "deepseek"  # 备用提供商：DeepSeek-V3
    OPENAI = "openai"      # 预留，暂未使用
    ANTHROPIC = "anthropic"  # 预留，暂未使用


@dataclass
class LLMRequest:
    """LLM请求参数"""
    messages: List[Dict[str, str]]  # 对话消息列表
    temperature: float = 0.1
    max_tokens: int = 16000  # 统一使用16000
    timeout: int = 180
    stream: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """LLM响应结果"""
    success: bool
    content: str
    error: Optional[str] = None
    tokens_used: Optional[int] = None
    model: Optional[str] = None
    latency: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMConfig:
    """LLM配置"""
    provider: LLMProvider = LLMProvider.DOUBAO  # 豆包2.0 Pro
    model: str = "doubao-seed-2-0-pro-260215"  # 豆包2.0 Pro
    api_key: Optional[str] = None
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"  # 豆包2.0 Pro
    temperature: float = 0.1
    max_tokens: int = 16000  # 统一使用16000
    timeout: int = 180
    max_concurrent: int = 3
    max_retries: int = 5
    request_interval: float = 2.0
    enable_cache: bool = False
    cache_ttl: int = 3600

    def __post_init__(self):
        """从环境变量读取配置，.env 文件中的变量会覆盖 dataclass 的默认值"""
        # 优先级：环境变量(.env 文件) > dataclass 默认值
        # → 环境变量覆盖使得无需修改代码即可调整配置
        if self.api_key is None:
            # LLM_API_KEY 优先，S1_API_KEY 为兼容旧配置的备选
            self.api_key = os.getenv("LLM_API_KEY") or os.getenv("S1_API_KEY")
        if os.getenv("LLM_MODEL"):
            self.model = os.getenv("LLM_MODEL")
        if os.getenv("LLM_BASE_URL"):
            self.base_url = os.getenv("LLM_BASE_URL")
        if os.getenv("LLM_TEMPERATURE"):
            temp = float(os.getenv("LLM_TEMPERATURE"))
            if 0 <= temp <= 2:
                self.temperature = temp
        if os.getenv("LLM_MAX_TOKENS"):
            self.max_tokens = int(os.getenv("LLM_MAX_TOKENS"))
        if os.getenv("LLM_MAX_RETRIES"):
            self.max_retries = int(os.getenv("LLM_MAX_RETRIES"))
        if os.getenv("LLM_REQUEST_INTERVAL"):
            self.request_interval = float(os.getenv("LLM_REQUEST_INTERVAL"))


class LLMClient:
    """
    统一的LLM客户端（使用直接 HTTP 请求）

    特性：
    - 支持豆包2.0 Pro模型（thinking 参数支持）
    - 支持DeepSeek-V3模型
    - 自动重试机制（指数退避）
    - 请求限流控制
    - 响应缓存（可选）
    - Token使用统计
    - 回调钩子（请求前/后/失败）

    使用示例：
    ```python
    config = LLMConfig()
    client = LLMClient(config)

    request = LLMRequest(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ]
    )
    response = await client.call(request)
    print(response.content)
    ```
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        # WHY: API 有并发限制，需要控制同时请求数，超出限制会导致 429 错误
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        # WHY: 限流机制的基础，记录上一次请求的时间戳，用于 _rate_limit() 计算等待时间
        self._last_request_time = 0
        # WHY: 缓存仅在 enable_cache=True 时开启，避免在不需要缓存的场景中占用内存
        self._cache = {} if config.enable_cache else None

        # 回调钩子
        self._before_call: Optional[Callable] = None
        self._after_call: Optional[Callable] = None
        self._on_error: Optional[Callable] = None

        # 初始化时打印配置（用于诊断）
        logger.info(f"[LLMClient] 初始化 LLM 客户端")
        logger.info(f"[LLMClient]   - Provider: {config.provider.value}")
        logger.info(f"[LLMClient]   - Model: {config.model}")
        logger.info(f"[LLMClient]   - Base URL: {config.base_url}")
        logger.info(f"[LLMClient]   - API Key: {'已设置 (' + str(len(config.api_key)) + ' 字符)' if config.api_key else '未设置'}")
        logger.info(f"[LLMClient]   - Temperature: {config.temperature}")
        logger.info(f"[LLMClient]   - Max Tokens: {config.max_tokens}")
        logger.info(f"[LLMClient]   - Timeout: {config.timeout}s")
        logger.info(f"[LLMClient]   - Max Retries: {config.max_retries}")
        logger.info(f"[LLMClient]   - Request Interval: {config.request_interval}s")

    def set_callbacks(
        self,
        before_call: Optional[Callable] = None,
        after_call: Optional[Callable] = None,
        on_error: Optional[Callable] = None
    ):
        """设置回调钩子"""
        self._before_call = before_call
        self._after_call = after_call
        self._on_error = on_error

    def _build_request_body(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float
    ) -> Dict[str, Any]:
        """
        构建请求体

        豆包 API 格式：
        {
            "model": "doubao-seed-2-0-pro-260215",
            "messages": [...],
            "thinking": {"type": "disabled"}
        }
        """
        body = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # WHY: 豆包模型默认开启深度思考，会消耗大量token，课程生成场景不需要推理过程，禁用以节省成本
        if self.config.provider == LLMProvider.DOUBAO:
            body["thinking"] = {"type": "disabled"}

        return body

    async def _call_api(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        timeout: int
    ) -> Dict[str, Any]:
        """
        直接调用 API（使用 httpx）
        """
        url = f"{self.config.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
        body = self._build_request_body(messages, max_tokens, temperature)

        # 打印请求体以验证 thinking 参数
        import json
        logger.info(f"[LLMClient] 请求体: {json.dumps(body, ensure_ascii=False, indent=2)}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    async def call(self, request: LLMRequest) -> LLMResponse:
        """
        调用LLM

        Args:
            request: LLM请求参数

        Returns:
            LLM响应结果
        """
        # ── 缓存检查段 ──
        # → 通过 MD5(messages + temperature) 生成缓存键，相同输入可命中缓存
        # → TTL 过期检查：time.time() - cached["time"] < cache_ttl，过期则丢弃
        if self._cache is not None:
            cache_key = self._get_cache_key(request)
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                if time.time() - cached["time"] < self.config.cache_ttl:
                    return LLMResponse(
                        success=True,
                        content=cached["content"],
                        model=self.config.model,
                        latency=0.0,
                        metadata={"cached": True}
                    )

        # ── 并发控制入口 ──
        # → Semaphore 控制同时进行的请求数不超过 max_concurrent
        async with self._semaphore:
            # WHY: API 有 QPS 限制，确保请求间隔不低于 request_interval
            await self._rate_limit()

            # 请求前回调
            if self._before_call:
                await self._before_call(request)

            start_time = time.time()

            # ── 重试循环 ──
            # → 指数退避策略：wait_time = 2^attempt * request_interval
            #   第1次重试等待 2^0 * interval = interval 秒
            #   第2次重试等待 2^1 * interval = 2*interval 秒
            #   第3次重试等待 2^2 * interval = 4*interval 秒 ...以此类推
            last_error = None
            for attempt in range(self.config.max_retries):
                try:
                    # 调用LLM（首次调用时打印详细配置）
                    if attempt == 0:
                        logger.info(f"[LLMClient] 调用 LLM API")
                        logger.info(f"[LLMClient]   - Provider: {self.config.provider.value}")
                        logger.info(f"[LLMClient]   - Model: {self.config.model}")
                        logger.info(f"[LLMClient]   - Base URL: {self.config.base_url}")
                        logger.info(f"[LLMClient]   - API Key: {'已设置' if self.config.api_key else '未设置'} ({len(self.config.api_key) if self.config.api_key else 0} 字符)")
                        logger.info(f"[LLMClient]   - Messages: {len(request.messages)} 条")

                    # → 动态 max_tokens：优先使用请求级别配置，其次使用全局配置
                    max_tokens_to_use = request.max_tokens or self.config.max_tokens
                    # WHY: API 硬限制 MAX_API_TOKENS=16384，超出会被拒绝
                    MAX_API_TOKENS = 16384
                    if max_tokens_to_use > MAX_API_TOKENS:
                        logger.warning(f"[LLMClient] 请求max_tokens({max_tokens_to_use})超过API限制({MAX_API_TOKENS})，将调整为{MAX_API_TOKENS}")
                        max_tokens_to_use = MAX_API_TOKENS

                    # 首次调用时记录使用的token数
                    if attempt == 0:
                        logger.info(f"[LLMClient]   - Max Tokens: {max_tokens_to_use} (请求: {request.max_tokens}, 默认: {self.config.max_tokens})")
                        if self.config.provider == LLMProvider.DOUBAO:
                            logger.info(f"[LLMClient]   - Thinking: disabled (豆包模型)")

                    # 直接调用 API
                    response_data = await self._call_api(
                        messages=request.messages,
                        max_tokens=max_tokens_to_use,
                        temperature=request.temperature or self.config.temperature,
                        timeout=request.timeout or self.config.timeout
                    )

                    # → 解析响应：从 choices[0].message.content 提取文本
                    message = response_data["choices"][0]["message"]
                    content = message["content"]

                    # WHY: 如果检测到 reasoning_content，说明 thinking 禁用未生效，需要警告
                    # → 深度思考会消耗大量额外 token，导致成本飙升
                    if "reasoning_content" in message:
                        reasoning = message["reasoning_content"]
                        logger.warning(f"[LLMClient] ⚠ 检测到思考内容 (长度: {len(reasoning)} 字符)")
                        logger.warning(f"[LLMClient] ⚠ thinking 参数可能未生效，深度思考未关闭")
                    else:
                        if self.config.provider == LLMProvider.DOUBAO:
                            logger.info(f"[LLMClient] ✓ 深度思考已关闭 (未检测到 reasoning_content)")

                    latency = time.time() - start_time

                    # 获取 token 使用量
                    tokens_used = None
                    if "usage" in response_data:
                        tokens_used = response_data["usage"].get("total_tokens")

                    logger.info(f"[LLMClient] ✓ API 调用成功 (耗时: {latency:.2f}s, Tokens: {tokens_used})")

                    result = LLMResponse(
                        success=True,
                        content=content,
                        tokens_used=tokens_used,
                        model=self.config.model,
                        latency=latency
                    )

                    # 缓存结果
                    if self._cache is not None:
                        self._cache[cache_key] = {
                            "content": content,
                            "time": time.time()
                        }

                    # 请求后回调
                    if self._after_call:
                        await self._after_call(request, result)

                    return result

                except httpx.HTTPStatusError as e:
                    # ── HTTP 错误诊断 ──
                    # → 401: API 密钥无效或已过期，需检查环境变量配置
                    # → 403: 访问被禁止，密钥权限不足或账户欠费
                    # → 429: API 速率限制，请求过于频繁，需增大 request_interval
                    last_error = e

                except Exception as e:
                    last_error = e
                    error_type = type(e).__name__
                    error_msg = str(e)

                    logger.error(f"[LLMClient] ✗ API 调用失败 (尝试 {attempt + 1}/{self.config.max_retries})")
                    logger.error(f"[LLMClient]   - 错误类型: {error_type}")
                    logger.error(f"[LLMClient]   - 错误信息: {error_msg}")

                    # 检查常见错误类型
                    if "timeout" in error_msg.lower() or "Timeout" in str(type(e)):
                        logger.error(f"[LLMClient]   - 诊断: 请求超时")
                        logger.error(f"[LLMClient]   - 解决: 检查网络连接或增加超时时间")
                    elif "connection" in error_msg.lower():
                        logger.error(f"[LLMClient]   - 诊断: 网络连接失败")
                        logger.error(f"[LLMClient]   - 解决: 检查网络或 API 地址 ({self.config.base_url})")

                if attempt < self.config.max_retries - 1:
                    # 指数退避
                    wait_time = (2 ** attempt) * self.config.request_interval
                    logger.warning(f"[LLMClient] 等待 {wait_time:.1f} 秒后重试...")
                    print(f"  [LLMClient] 重试 {attempt + 1}/{self.config.max_retries}, 等待 {wait_time:.1f}秒")
                    await asyncio.sleep(wait_time)
                else:
                    # 最后一次尝试也失败了
                    logger.error(f"[LLMClient] ✗ 所有重试均失败 ({self.config.max_retries}/{self.config.max_retries})")
                    # 失败回调
                    if self._on_error:
                        await self._on_error(request, last_error)

            # 全部重试失败
            return LLMResponse(
                success=False,
                content="",
                error=str(last_error),
                model=self.config.model,
                latency=time.time() - start_time
            )

    async def call_with_history(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> LLMResponse:
        """
        使用消息历史调用LLM（便捷方法）

        Args:
            messages: 消息历史列表
            **kwargs: 其他请求参数

        Returns:
            LLM响应结果
        """
        request = LLMRequest(messages=messages, **kwargs)
        return await self.call(request)

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> LLMResponse:
        """
        使用系统提示和用户提示调用LLM（便捷方法）

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            **kwargs: 其他请求参数

        Returns:
            LLM响应结果
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return await self.call_with_history(messages, **kwargs)

    async def _rate_limit(self):
        """请求限流"""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.config.request_interval:
            await asyncio.sleep(self.config.request_interval - elapsed)
        self._last_request_time = time.time()

    def _get_cache_key(self, request: LLMRequest) -> str:
        """生成缓存键"""
        import hashlib
        content = str(request.messages) + str(request.temperature)
        return hashlib.md5(content.encode()).hexdigest()

    def clear_cache(self):
        """清空缓存"""
        if self._cache is not None:
            self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        cache_size = len(self._cache) if self._cache else 0
        return {
            "cache_size": cache_size,
            "config": {
                "model": self.config.model,
                "provider": self.config.provider.value,
                "max_concurrent": self.config.max_concurrent,
                "max_retries": self.config.max_retries,
                "request_interval": self.config.request_interval,
            }
        }

    async def test_connection(self) -> Dict[str, Any]:
        """
        测试 API 连接

        发送一个简单的测试请求来验证 API 连接是否正常

        Returns:
            包含测试结果的字典：
            {
                "success": bool,
                "message": str,
                "latency": float,
                "error": str (如果失败)
            }
        """
        logger.info(f"[LLMClient] ========== API 连接测试 ==========")
        logger.info(f"[LLMClient] 测试目标: {self.config.base_url}")
        logger.info(f"[LLMClient] 模型: {self.config.model}")

        start_time = time.time()
        try:
            # 发送一个简单的测试请求
            test_request = LLMRequest(
                messages=[
                    {"role": "user", "content": "Hi"}
                ],
                max_tokens=10,  # 最小 token 数
                timeout=10  # 10 秒超时
            )

            response = await self.call(test_request)

            latency = time.time() - start_time

            if response.success:
                logger.info(f"[LLMClient] ✓ API 连接测试成功 (耗时: {latency:.2f}s)")
                return {
                    "success": True,
                    "message": "API 连接正常",
                    "latency": latency
                }
            else:
                logger.error(f"[LLMClient] ✗ API 连接测试失败: {response.error}")
                return {
                    "success": False,
                    "message": "API 连接失败",
                    "error": response.error,
                    "latency": latency
                }

        except Exception as e:
            latency = time.time() - start_time
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(f"[LLMClient] ✗ API 连接测试异常")
            logger.error(f"[LLMClient]   - 错误类型: {error_type}")
            logger.error(f"[LLMClient]   - 错误信息: {error_msg}")

            # 诊断建议
            if "401" in error_msg:
                logger.error(f"[LLMClient] 诊断: API 密钥无效")
            elif "connection" in error_msg.lower():
                logger.error(f"[LLMClient] 诊断: 网络连接问题")
            elif "timeout" in error_msg.lower():
                logger.error(f"[LLMClient] 诊断: 请求超时")

            return {
                "success": False,
                "message": f"测试异常: {error_type}",
                "error": error_msg,
                "latency": latency
            }


# ==================== 便捷函数 ====================

async def call_llm(
    messages: List[Dict[str, str]],
    api_key: str = None,
    model: str = "doubao-seed-2-0-pro-260215",
    **kwargs
) -> LLMResponse:
    """
    简便的LLM调用函数（无需创建客户端实例）

    Args:
        messages: 消息列表
        api_key: API密钥（可选，默认从环境变量读取）
        model: 模型名称
        **kwargs: 其他请求参数

    Returns:
        LLM响应结果

    使用示例：
    ```python
    response = await call_llm([
        {"role": "system", "content": "You are a math teacher."},
        {"role": "user", "content": "Explain fractions."}
    ])
    print(response.content)
    ```
    """
    config = LLMConfig(
        api_key=api_key,
        model=model,
        **kwargs
    )
    client = LLMClient(config)
    return await client.call(LLMRequest(messages=messages))

