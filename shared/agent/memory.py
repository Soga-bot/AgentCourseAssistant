"""
记忆管理器 - 为Agent提供短期和长期记忆

记忆机制是Agent的重要特性，允许Agent：
- 存储和检索信息
- 在多次对话之间保持上下文
- 实现个性化的交互

双层存储架构
============
短期记忆（Short-term）：
    - 存储在内存中的 Dict 结构（self._short_term）
    - 生命周期为会话级别，进程退出即丢失
    - 读写速度极快，无 IO 开销
    - 结构：{agent_id: {key: MemoryItem}}

长期记忆（Long-term / Persisted）：
    - 持久化到磁盘上的 JSON 文件（self.persist_dir / "{agent_id}.json"）
    - 跨会话保留，进程重启后依然可用
    - 每次读写涉及文件 IO，速度相对较慢

查找顺序：
    1. 先查短期记忆（内存 Dict）→ 命中则直接返回
    2. 未命中则查持久化存储（磁盘 JSON 文件）
    3. 在持久化中找到后回填到短期缓存，避免后续重复 IO
"""
from typing import Dict, Any, Optional, List
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import uuid

logger = logging.getLogger(__name__)


@dataclass
class MemoryItem:
    """记忆项

    表示一条存储的记忆
    """
    key: str
    value: Any
    timestamp: str
    ttl: Optional[int] = None  # 过期时间（秒）。None 表示永不过期；设为具体秒数后，经过该时间即视为过期
    agent_id: str = ""

    def is_expired(self) -> bool:
        """检查记忆是否过期

        过期判定逻辑：
            当前时间 > 创建时间（timestamp） + 生存时间（ttl）
            - ttl 为 None 时永不过期，直接返回 False
            - timestamp 解析失败时保守地返回 False（不丢弃记忆）
        """
        # ttl 为 None 表示永不过期，直接返回
        if self.ttl is None:
            return False

        try:
            # 将 ISO 格式字符串解析为 datetime，再加上 ttl 秒得到过期时间点
            timestamp = datetime.fromisoformat(self.timestamp)
            expiry = timestamp + timedelta(seconds=self.ttl)
            # 当前时间超过过期时间点 → 已过期
            return datetime.now() > expiry
        except Exception:
            # timestamp 解析异常时保守处理，不判定为过期
            return False

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)


class MemoryManager:
    """
    记忆管理器

    提供：
    - 短期记忆（内存中，会话级别）
    - 长期记忆（持久化存储）
    - 上下文窗口管理
    - TTL过期机制

    使用示例：
        memory = MemoryManager()

        # 存储记忆
        memory.store("agent_1", "user_name", "张三")

        # 检索记忆
        name = memory.retrieve("agent_1", "user_name")

        # 获取上下文记忆
        context = memory.get_context("agent_1", max_items=10)
    """

    def __init__(self, persist_dir: Optional[Path] = None):
        """
        初始化记忆管理器

        Args:
            persist_dir: 持久化存储目录
        """
        self.persist_dir = persist_dir or Path("./data/memories")
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # 短期记忆（内存）
        # 结构: {agent_id: {key: MemoryItem}}
        self._short_term: Dict[str, Dict[str, MemoryItem]] = {}

        logger.info(f"[MemoryManager] Initialized with persist_dir: {self.persist_dir}")

    def store(
        self,
        agent_id: str,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        persist: bool = False
    ):
        """
        存储记忆

        Args:
            agent_id: Agent ID
            key: 记忆键
            value: 记忆值
            ttl: 过期时间（秒），None表示永不过期
            persist: 是否持久化到磁盘
        """
        # WHY: 大部分记忆只需短期存在（如本轮对话的临时变量），
        #      只有关键信息如学情记录、用户偏好等才需持久化到磁盘，
        #      因此 persist 默认为 False，由调用方按需显式开启
        if agent_id not in self._short_term:
            self._short_term[agent_id] = {}

        # → 创建记忆条目，记录当前时间戳用于过期判定和排序
        memory = MemoryItem(
            key=key,
            value=value,
            timestamp=datetime.now().isoformat(),
            ttl=ttl,
            agent_id=agent_id
        )

        # → 先写入短期记忆（内存），保证立即可用
        self._short_term[agent_id][key] = memory

        if persist:
            # → 再追加写入持久化文件（磁盘），保证跨会话可用
            self._persist(agent_id, key, memory)

        logger.debug(f"[MemoryManager] Stored: {agent_id}/{key}")

    def retrieve(self, agent_id: str, key: str) -> Optional[Any]:
        """
        检索记忆

        查找顺序：
            1. 先查短期记忆（内存 Dict）→ 命中且未过期则直接返回
            2. 未命中则查持久化存储（磁盘 JSON 文件）
            3. 持久化中找到后回填到短期缓存，后续访问不再走 IO

        Args:
            agent_id: Agent ID
            key: 记忆键

        Returns:
            记忆值，如果不存在或已过期则返回None
        """
        # 第一步：从短期记忆查找（内存，零 IO 开销）
        if agent_id in self._short_term and key in self._short_term[agent_id]:
            memory = self._short_term[agent_id][key]

            # 检查是否过期 → 已过期则清除并返回 None
            if memory.is_expired():
                logger.debug(f"[MemoryManager] Memory expired: {agent_id}/{key}")
                del self._short_term[agent_id][key]
                return None

            # → 短期命中，直接返回值
            return memory.value

        # 第二步：从持久化存储查找（磁盘 JSON 文件）
        # → 若命中会自动回填短期缓存，见 _retrieve_persisted 实现
        return self._retrieve_persisted(agent_id, key)

    def get_context(
        self,
        agent_id: str,
        max_items: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取Agent的上下文记忆

        返回最近的N条记忆，用于构建提示词

        # → 注入到 ReAct 的 system prompt 中，为 Agent 提供历史上下文
        #    排序策略：按时间倒序（reverse=True），最近的记忆排在最前面，
        #    因为最近的记忆通常与当前对话最相关

        Args:
            agent_id: Agent ID
            max_items: 最大记忆数量

        Returns:
            记忆列表，按时间倒序排列
        """
        if agent_id not in self._short_term:
            return []

        memories = self._short_term[agent_id]

        # 过滤掉已过期的记忆，只保留有效条目
        valid_memories = [
            m for m in memories.values()
            if not m.is_expired()
        ]

        # 按时间戳降序排序（最新的在前），截取 max_items 条
        # WHY: 时间倒序保证最近的记忆排在前面，与当前对话最相关
        sorted_memories = sorted(
            valid_memories,
            key=lambda m: m.timestamp,
            reverse=True
        )[:max_items]

        # → 返回精简的字典列表，仅包含 key/value/timestamp，不含 ttl 等内部字段
        return [
            {
                "key": m.key,
                "value": m.value,
                "timestamp": m.timestamp
            }
            for m in sorted_memories
        ]

    def delete(self, agent_id: str, key: str):
        """
        删除指定记忆

        Args:
            agent_id: Agent ID
            key: 记忆键
        """
        if agent_id in self._short_term and key in self._short_term[agent_id]:
            del self._short_term[agent_id][key]
            logger.debug(f"[MemoryManager] Deleted: {agent_id}/{key}")

    def clear(self, agent_id: str):
        """
        清除Agent的所有记忆

        Args:
            agent_id: Agent ID
        """
        if agent_id in self._short_term:
            del self._short_term[agent_id]

        # 清除持久化文件
        persist_file = self.persist_dir / f"{agent_id}.json"
        if persist_file.exists():
            persist_file.unlink()
            logger.debug(f"[MemoryManager] Deleted persisted memory: {agent_id}")

        logger.info(f"[MemoryManager] Cleared all memory for {agent_id}")

    def get_all_keys(self, agent_id: str) -> List[str]:
        """
        获取Agent的所有记忆键

        Args:
            agent_id: Agent ID

        Returns:
            记忆键列表
        """
        if agent_id not in self._short_term:
            return []

        # 过滤过期记忆
        valid_keys = [
            key for key, memory in self._short_term[agent_id].items()
            if not memory.is_expired()
        ]

        return valid_keys

    def _persist(self, agent_id: str, key: str, memory: MemoryItem):
        """
        持久化记忆

        持久化文件格式：
            - 每个 Agent 对应一个 JSON 文件，路径为 {persist_dir}/{agent_id}.json
            - JSON 结构为 {"key1": MemoryItem字典, "key2": MemoryItem字典, ...}
            - 每次写入采用"读取 → 合并 → 全量写回"策略

        Args:
            agent_id: Agent ID
            key: 记忆键
            memory: 记忆项
        """
        # → 每个 Agent 一个独立 JSON 文件，互不干扰
        persist_file = self.persist_dir / f"{agent_id}.json"

        # 读取现有持久化数据（全量读取）
        existing = {}
        if persist_file.exists():
            try:
                existing = json.loads(persist_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[MemoryManager] Failed to read persisted memory: {e}")
                existing = {}

        # → 将当前记忆条目合并到已有数据中（key 相同则覆盖更新）
        existing[key] = memory.to_dict()

        # → 全量写回磁盘，ensure_ascii=False 保留中文可读性，indent=2 方便调试
        try:
            persist_file.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"[MemoryManager] Failed to persist memory: {e}")

    def _retrieve_persisted(self, agent_id: str, key: str) -> Optional[Any]:
        """
        从持久化存储检索

        回填机制：
            从磁盘 JSON 文件读取到记忆后，同步写入短期记忆（self._short_term），
            这样后续对同一 key 的访问就能直接命中内存，避免重复的文件 IO。

        Args:
            agent_id: Agent ID
            key: 记忆键

        Returns:
            记忆值，如果不存在或已过期则返回None
        """
        persist_file = self.persist_dir / f"{agent_id}.json"

        # → 持久化文件不存在，说明该 Agent 从未持久化过记忆
        if not persist_file.exists():
            return None

        try:
            data = json.loads(persist_file.read_text(encoding="utf-8"))

            if key in data:
                # → 从 JSON 字典中反序列化为 MemoryItem 对象
                memory_data = data[key]
                memory = MemoryItem(**memory_data)

                if not memory.is_expired():
                    # → 回填到短期记忆：磁盘 → 内存缓存，后续访问免 IO
                    if agent_id not in self._short_term:
                        self._short_term[agent_id] = {}
                    self._short_term[agent_id][key] = memory

                    return memory.value

        except Exception as e:
            logger.error(f"[MemoryManager] Failed to retrieve persisted memory: {e}")

        return None

    def load_persisted(self, agent_id: str) -> int:
        """
        加载Agent的所有持久化记忆

        加载时机：
            在 Agent 初始化时调用此方法，将上一次会话持久化的记忆全部恢复到短期缓存中，
            使 Agent 能够在新会话中立即访问历史上下文（如学情记录、用户偏好等）。

        Args:
            agent_id: Agent ID

        Returns:
            加载的记忆数量（已过期的记忆不计入）
        """
        persist_file = self.persist_dir / f"{agent_id}.json"

        # → 无持久化文件说明该 Agent 无历史记忆，直接返回
        if not persist_file.exists():
            return 0

        try:
            data = json.loads(persist_file.read_text(encoding="utf-8"))

            count = 0
            for key, memory_data in data.items():
                memory = MemoryItem(**memory_data)

                # 跳过已过期的记忆，不恢复到短期缓存
                if memory.is_expired():
                    continue

                # → 将有效记忆批量回填到短期缓存，恢复历史上下文
                if agent_id not in self._short_term:
                    self._short_term[agent_id] = {}

                self._short_term[agent_id][key] = memory
                count += 1

            logger.info(f"[MemoryManager] Loaded {count} persisted memories for {agent_id}")
            return count

        except Exception as e:
            logger.error(f"[MemoryManager] Failed to load persisted memory: {e}")
            return 0

    def __repr__(self) -> str:
        agent_count = len(self._short_term)
        total_memories = sum(len(mems) for mems in self._short_term.values())
        return f"<MemoryManager agents={agent_count} memories={total_memories}>"
