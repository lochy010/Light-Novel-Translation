# cache/cache_manager.py
"""
缓存管理模块
功能：实现智能会话级缓存管理，支持缓存生命周期管理、自动清理和跨会话隔离
核心机制：
- 使用线程安全的锁机制保证并发安全
- 支持JSON文件持久化存储缓存数据
- 基于文件哈希实现会话级缓存隔离
- 提供缓存命中检测、自动清理和会话关联管理
"""

import os
import json
import threading
import hashlib
from config.settings import PATH_CONFIG  # 新增配置导入


class TranslationCache:
    """翻译缓存管理系统

    属性：
    - cache: 存储所有缓存数据的字典，结构为 {md5_key: translation_result}
    - session_map: 会话映射表，记录文件哈希与缓存键的关联关系
    - cache_file: 持久化缓存文件的路径（从配置读取默认值）
    - lock: 线程锁，确保多线程操作安全

    功能：
    - 自动加载/保存持久化缓存
    - 生成唯一缓存键
    - 缓存读写操作
    - 会话级缓存管理
    """

    def __init__(self, cache_file=PATH_CONFIG["CACHE_FILE"]):  # 修改默认值来源
        """初始化缓存系统
        :param cache_file: 缓存文件路径，默认使用配置文件中 PATH_CONFIG["CACHE_FILE"]
        """
        self.cache = {}  # 缓存数据存储字典
        self.session_map = {}  # 会话映射关系 {file_hash: [cache_key1, ...]}
        self.cache_file = cache_file
        self.lock = threading.Lock()  # 线程安全锁
        self.load_cache()  # 初始化时加载持久化缓存

    def load_cache(self):
        """从磁盘加载持久化缓存数据
        异常处理：捕获文件不存在或格式错误等异常，打印错误信息但不会中断程序
        """
        try:
            # 使用线程锁保证加载操作的原子性
            with self.lock:
                if os.path.exists(self.cache_file):
                    with open(self.cache_file, "r", encoding="utf-8") as f:
                        self.cache = json.load(f)
                        print(f"成功加载缓存文件，共 {len(self.cache)} 条缓存记录")
        except Exception as e:
            print(f"[ERROR] 加载缓存失败: {str(e)}")

    def save_cache(self, force=False):
        """将缓存数据持久化到文件
        :param force: 保留参数，用于未来扩展强制保存逻辑
        """
        # 使用线程锁保证写入操作的原子性
        with self.lock:
            try:
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    # 美化输出格式，禁用ASCII转义，2空格缩进
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
                    print(f"缓存已持久化，当前缓存数量：{len(self.cache)}")
            except Exception as e:
                print(f"[ERROR] 保存缓存失败: {str(e)}")

    def get_key(self, text, lang, style, file_hash=None):
        """生成唯一缓存键
        算法逻辑：文本内容+目标语言+翻译风格+文件哈希（可选）的MD5摘要

        :param text: 原始文本内容
        :param lang: 目标语言代码（如zh/en）
        :param style: 翻译风格标识（如standard/light_novel）
        :param file_hash: 文件哈希值，用于会话隔离（可选）
        :return: 32位十六进制MD5哈希字符串
        """
        # 拼接关键参数作为键值基础
        key_str = f"{text}{lang}{style}"
        # 会话级缓存需包含文件特征码
        if file_hash is not None:
            key_str += file_hash
        # 生成MD5摘要
        return hashlib.md5(key_str.encode("utf-8")).hexdigest()

    def get(self, text, lang, style, file_hash=None, log_callback=None):
        """获取缓存内容
        功能流程：
        1. 计算缓存键
        2. 查询缓存字典
        3. 触发缓存命中回调（用于GUI日志）

        :param log_callback: 日志回调函数，接收缓存命中消息
        :return: 存在则返回缓存值，否则返回None
        """
        key = self.get_key(text, lang, style, file_hash)
        translation = self.cache.get(key)
        # 触发GUI日志回调
        if translation and log_callback:
            log_callback("💾 缓存命中，跳过翻译")
        return translation

    def set(self, text, lang, style, translation, file_hash=None):
        """设置缓存内容
        功能流程：
        1. 计算缓存键
        2. 更新缓存字典
        3. 记录会话关联（如果提供文件哈希）
        4. 触发持久化保存

        :param file_hash: 文件哈希值，用于会话关联（可选）
        """
        key = self.get_key(text, lang, style, file_hash)
        # 使用线程锁保证写入安全
        with self.lock:
            self.cache[key] = translation
        # 记录会话关联关系
        if file_hash is not None:
            self.record_session(file_hash, key)
        self.save_cache()  # 异步保存

    def record_session(self, file_hash, cache_key):
        """记录缓存与会话的关联关系
        结构：session_map[file_hash] = [cache_key1, cache_key2...]
        """
        with self.lock:
            if file_hash not in self.session_map:
                self.session_map[file_hash] = []
            # 避免重复记录
            if cache_key not in self.session_map[file_hash]:
                self.session_map[file_hash].append(cache_key)

    def purge_session_cache(self, file_hash):
        """清理指定会话的全部缓存
        操作流程：
        1. 从session_map获取该会话所有缓存键
        2. 批量删除cache中的对应条目
        3. 删除session_map中的会话记录
        4. 触发持久化保存
        """
        with self.lock:
            if file_hash in self.session_map:
                # 批量删除缓存条目
                for key in self.session_map[file_hash]:
                    self.cache.pop(key, None)
                # 删除会话记录
                del self.session_map[file_hash]
                self.save_cache()

    def clear_all_cache(self):
        """
        清空全部缓存数据
        功能描述：
        1. 清空内存中的缓存数据（`self.cache` 和 `self.session_map`）
        2. 清空持久化缓存文件，并将其保存为空的 JSON 文件
        3. 提供清空成功的确认信息或错误消息并抛出异常

        流程步骤：
        - 使用线程锁 `self.lock` 保证操作的原子性
        - 调用 `clear()` 方法清空 `self.cache` 和 `self.session_map`
        - 打开缓存文件 `self.cache_file`，清空内容并保存 `{}`（空字典）为 JSON 格式
        - 如操作成功，打印成功信息；如操作失败，捕获异常并打印错误消息，同时抛出异常
        """
        with self.lock:
            self.cache.clear()
            self.session_map.clear()
            try:
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump({}, f, indent=2)
                print("成功清空所有缓存数据")
            except Exception as e:
                print(f"[ERROR] 清空缓存失败: {str(e)}")
                raise