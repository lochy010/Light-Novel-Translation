# cache/cache_manager.py
"""
缓存管理模块 (cache_manager.py)

功能：
该模块负责实现一个智能的、会话级别的翻译缓存系统。它旨在通过存储和复用之前的翻译结果来减少不必要的 API 调用，
从而提高效率并降低成本。支持缓存数据的持久化存储、基于文件内容的缓存隔离、缓存生命周期管理和并发安全。

核心机制：
- 使用线程锁 (`threading.Lock`) 来保证在多线程环境下对缓存数据的访问是安全的。
- 将缓存数据（包括翻译结果和会话映射）序列化为 JSON 格式，并持久化存储到磁盘文件中。
- 通过计算输入文件的 MD5 哈希值，实现不同文件（或同一文件的不同版本）之间的缓存隔离。
- 提供缓存的读取 (`get`)、写入 (`set`)、基于会话的清除 (`purge_session_cache`) 以及完全清除 (`clear_all_cache`) 的功能。
- 包含加载 (`load_cache`) 和保存 (`save_cache`) 缓存数据的逻辑。
- 记录详细的操作日志，便于追踪缓存行为和调试问题。
"""

# 导入 os 模块，用于处理文件和目录路径、检查文件存在性、获取文件大小以及创建目录等。
import os
# 导入 json 模块，用于将 Python 字典序列化为 JSON 字符串写入文件，以及从 JSON 文件解析数据回 Python 对象。
import json
# 导入 threading 模块，主要使用 Lock 类来创建线程锁，确保缓存读写操作的原子性，防止多线程冲突。
import threading
# 导入 hashlib 模块，用于计算 MD5 哈希值，生成缓存键或文件特征码。
import hashlib
# 导入 logging 模块，用于记录程序运行时的信息、警告和错误。
import logging

# 导入配置文件中的路径设置
# settings 模块包含了应用程序所需的各种配置常量，这里主要用到缓存文件的默认路径。
from config.settings import PATH_CONFIG

# --- 获取日志记录器实例 ---
# 获取一个名为 'cache_manager' 的日志记录器实例。
# 日志的格式化将在主程序入口 (main.py) 中统一设置，这里仅获取记录器。
logger = logging.getLogger(__name__) # 使用当前模块名作为记录器名称

# --- 翻译缓存管理类 ---
class TranslationCache:
    """
    翻译缓存管理系统类。

    负责管理翻译结果的缓存，包括内存中的数据结构、与磁盘文件的交互以及会话管理。

    属性:
        cache (dict): 存储核心缓存数据。键是根据文本、语言、风格和文件哈希生成的 MD5 缓存键 (str)，值是对应的翻译结果 (str)。
                      结构: {md5_key: translation_result}
        session_map (dict): 维护文件哈希与该文件关联的所有缓存键之间的映射关系。键是文件内容的 MD5 哈希值 (str)，
                            值是一个包含与该文件相关的所有缓存键 (str) 的列表。
                            结构: {file_hash: [cache_key1, cache_key2, ...]}
                            这个映射表也会被持久化到 JSON 文件中。
        cache_file (str): 持久化缓存数据（包括 cache 和 session_map）的 JSON 文件的完整路径。
                          默认值从 config.settings.PATH_CONFIG 中读取。
        lock (threading.Lock): 线程锁对象，用于保护对 cache 和 session_map 的并发访问，确保线程安全。
    """

    def __init__(self, cache_file=PATH_CONFIG["CACHE_FILE"]):
        """
        初始化 TranslationCache 类的实例。

        - 设置实例变量的初始状态（空字典、锁对象）。
        - 确定并记录缓存文件的路径。
        - 记录初始化过程的日志信息。

        参数:
            cache_file (str, optional): 指定缓存文件的路径。如果未提供，则使用 `config.settings.PATH_CONFIG` 中定义的 "CACHE_FILE" 值。
                                        默认为 `PATH_CONFIG["CACHE_FILE"]`。
        """
        logger.info("--- TranslationCache 初始化开始 ---")
        # 初始化内存中的缓存字典
        self.cache = {}
        # 初始化内存中的会话映射字典
        self.session_map = {}
        # 设置缓存文件的路径
        self.cache_file = cache_file
        logger.info(f"缓存文件路径设置为: {self.cache_file}")
        # 创建线程锁实例
        self.lock = threading.Lock()
        # 记录实例创建信息，此时缓存数据尚未加载
        logger.info("TranslationCache 实例已创建，缓存数据将在 load_cache() 调用时加载。")
        logger.info("--- TranslationCache 初始化完成 ---")

    def load_cache(self):
        """
        从磁盘上的 JSON 文件加载持久化的缓存数据（包括 `cache` 和 `session_map`）。

        执行流程：
        1.  获取线程锁，确保加载过程的线程安全。
        2.  检查指定的缓存文件是否存在。
        3.  如果文件存在，检查文件大小是否大于 0。
        4.  如果文件存在且非空，尝试以 UTF-8 编码打开并使用 `json.load()` 解析文件内容。
        5.  根据解析出的数据结构：
            -   如果是包含 "cache" 和 "session_map" 键的字典（新格式），则加载对应的数据到实例变量。会检查内部数据类型是否正确。
            -   如果是字典但不包含特定键（旧格式，只存了 cache 数据），则加载数据到 `self.cache`，`self.session_map` 初始化为空。
            -   如果根元素不是字典，则无法解析，初始化为空缓存和会话映射。
        6.  处理可能发生的错误：
            -   文件不存在：初始化为空缓存和会话映射。
            -   文件为空：初始化为空缓存和会话映射。
            -   获取文件大小失败 (OSError)：初始化为空缓存和会话映射。
            -   JSON 解析错误 (json.JSONDecodeError)：初始化为空缓存和会话映射。
            -   其他文件读取或解析错误 (Exception)：初始化为空缓存和会话映射。
        7.  记录详细的加载过程日志，包括文件状态、大小、加载结果或遇到的错误。
        8.  在 `finally` 块中释放线程锁。
        """
        logger.info("[Cache Load] --- 开始加载缓存文件 ---")
        logger.info(f"[Cache Load] 尝试加载文件: {self.cache_file}")
        try:
            # 获取锁，确保加载期间其他线程不能修改缓存
            with self.lock:
                # 检查缓存文件物理上是否存在
                if os.path.exists(self.cache_file):
                    try:
                        # 获取文件大小，用于判断是否为空文件
                        file_size = os.path.getsize(self.cache_file)
                        logger.info(f"[Cache Load] 缓存文件存在，大小: {file_size} 字节。")

                        # 仅当文件大小大于0时才尝试读取
                        if file_size > 0:
                            logger.info("[Cache Load] 文件非空，尝试读取并解析 JSON...")
                            # 以只读模式 ('r') 和 UTF-8 编码打开文件
                            with open(self.cache_file, "r", encoding="utf-8") as f:
                                try:
                                    # 解析 JSON 文件内容到 Python 对象 (通常是字典)
                                    data = json.load(f)
                                    logger.info("[Cache Load] JSON 文件加载成功，开始解析数据结构...")

                                    # 检查是否为新格式（包含 'cache' 和 'session_map' 的字典）
                                    if isinstance(data, dict) and "cache" in data and "session_map" in data:
                                        logger.info("[Cache Load] 检测到新格式缓存文件 (包含 'cache' 和 'session_map' 键)。")
                                        # 验证 'cache' 值的类型，必须是字典
                                        if isinstance(data["cache"], dict):
                                             self.cache = data["cache"]
                                             logger.debug("[Cache Load] 'cache' 数据加载成功。")
                                        else:
                                             logger.warning("[Cache Load] 缓存文件中 'cache' 数据格式无效 (非字典)，将初始化为空缓存。")
                                             self.cache = {} # 数据无效，重置
                                        # 验证 'session_map' 值的类型，必须是字典
                                        if isinstance(data["session_map"], dict):
                                            self.session_map = data["session_map"]
                                            logger.debug("[Cache Load] 'session_map' 数据加载成功。")
                                        else:
                                            logger.warning("[Cache Load] 缓存文件中 'session_map' 数据格式无效 (非字典)，将初始化为空会话映射。")
                                            self.session_map = {} # 数据无效，重置
                                        # 记录加载成功的信息和统计数据
                                        logger.info(f"[Cache Load] 成功加载新格式缓存。缓存条目数: {len(self.cache)}, 会话映射数: {len(self.session_map)}")

                                    # 检查是否为旧格式（仅包含缓存数据的字典）
                                    elif isinstance(data, dict):
                                         logger.warning("[Cache Load] 检测到旧格式缓存文件 (仅含缓存数据或结构不完整)。")
                                         logger.warning("[Cache Load] 将加载缓存数据，并初始化空的会话映射表。")
                                         # 加载数据到 cache，session_map 保持为空
                                         self.cache = data
                                         self.session_map = {}
                                         logger.info(f"[Cache Load] 成功加载旧格式缓存。缓存条目数: {len(self.cache)}, 会话映射数: 0")

                                    # 如果根元素不是字典，无法识别格式
                                    else:
                                         logger.warning("[Cache Load] 缓存文件根元素不是 JSON 对象 (字典)，无法解析。将初始化为空缓存和会话映射。")
                                         self.cache = {}; self.session_map = {} # 重置

                                # 处理 JSON 文件内容格式错误
                                except json.JSONDecodeError as json_err:
                                    logger.error(f"[Cache Load] 加载缓存失败：JSON 解析错误。错误信息: {json_err}。文件路径: {self.cache_file}", exc_info=False) # 通常不需要完整堆栈
                                    logger.error("[Cache Load] 将初始化为空缓存和会话映射。")
                                    self.cache = {}; self.session_map = {} # 重置
                                # 处理解析过程中其他可能的异常
                                except Exception as parse_err:
                                    logger.error(f"[Cache Load] 解析缓存文件内容时发生意外错误: {parse_err}", exc_info=True) # 记录堆栈
                                    logger.error("[Cache Load] 将初始化为空缓存和会话映射。")
                                    self.cache = {}; self.session_map = {} # 重置
                        # 如果文件大小为 0
                        else:
                            logger.info(f"[Cache Load] 缓存文件为空，初始化为空缓存和会话映射。")
                            self.cache = {}; self.session_map = {} # 重置
                    # 处理获取文件大小时的 OS 错误
                    except OSError as size_err:
                        logger.error(f"[Cache Load] 无法获取缓存文件大小: {size_err}。文件路径: {self.cache_file}", exc_info=False)
                        logger.error("[Cache Load] 将初始化为空缓存和会话映射。")
                        self.cache = {}; self.session_map = {} # 重置
                # 如果缓存文件不存在
                else:
                     logger.info(f"[Cache Load] 缓存文件不存在，初始化为空缓存和会话映射。预期路径: {self.cache_file}")
                     self.cache = {}; self.session_map = {} # 重置
        # 处理加载过程中其他外部错误，如文件访问权限问题
        except Exception as e:
            logger.error(f"[Cache Load] 加载缓存过程中发生意外错误 (如文件访问权限等): {e}", exc_info=True)
            logger.error("[Cache Load] 因外部错误，强制初始化为空缓存和会话映射。")
            self.cache = {}; self.session_map = {} # 重置
        finally:
            # 无论成功或失败，都记录加载流程结束
            logger.info("[Cache Load] --- 缓存加载流程结束 ---")

    def save_cache(self):
        """
        将当前的内存缓存数据 (`self.cache` 和 `self.session_map`) 持久化到 JSON 文件。

        注意：此方法假定调用它的外部代码（例如 `set` 或 `purge_session_cache` 方法）已经获取了线程锁 (`self.lock`)。

        执行流程：
        1.  获取缓存文件所在的目录路径。
        2.  如果目录不存在，尝试创建该目录。如果创建失败，记录错误并中止保存。
        3.  将 `self.cache` 和 `self.session_map` 打包到一个字典中。
        4.  记录准备写入的数据量（缓存条目数和会话映射数）。
        5.  以写入模式 ('w') 和 UTF-8 编码打开缓存文件。
        6.  使用 `json.dump()` 将打包后的数据写入文件，设置 `ensure_ascii=False` 以支持非 ASCII 字符，`indent=2` 用于格式化输出，便于阅读。
        7.  记录写入成功的日志。
        8.  尝试获取保存后文件的大小并记录。
        9.  处理可能发生的异常（如目录创建失败、文件写入 IO 错误、JSON 序列化错误等），并记录错误日志。
        10. 记录保存流程结束的日志。
        """
        logger.info("[Cache Save] --- 开始保存缓存文件 ---")
        logger.debug(f"[Cache Save] 准备保存到文件: {self.cache_file}")
        try:
            # 获取缓存文件所在的目录
            cache_dir = os.path.dirname(self.cache_file)
            # 如果目录路径非空（即缓存文件不在当前目录）且目录不存在
            if cache_dir and not os.path.exists(cache_dir):
                 logger.info(f"[Cache Save] 缓存目录不存在，尝试创建: {cache_dir}")
                 try:
                     # 创建目录，包括任何必要的父目录
                     os.makedirs(cache_dir)
                     logger.info(f"[Cache Save] 缓存目录创建成功: {cache_dir}")
                 except OSError as dir_err:
                      # 如果目录创建失败，记录错误并停止保存操作
                      logger.error(f"[Cache Save] 无法创建缓存目录 '{cache_dir}': {dir_err}", exc_info=True)
                      logger.error("[Cache Save] --- 缓存保存失败 (目录创建错误) ---")
                      return # 中止保存

            # 准备要保存的数据结构
            data_to_save = { "cache": self.cache, "session_map": self.session_map }
            # 记录当前缓存和会话映射的数量
            current_cache_count = len(self.cache)
            current_session_count = len(self.session_map)
            logger.debug(f"[Cache Save] 准备写入数据: {current_cache_count} 个缓存条目, {current_session_count} 个会话映射。")

            # 以写入模式 ('w') 和 UTF-8 编码打开缓存文件
            # 'w' 模式会覆盖已存在的文件内容
            with open(self.cache_file, "w", encoding="utf-8") as f:
                # 将 Python 字典写入 JSON 文件
                # ensure_ascii=False 保证中文等非 ASCII 字符按原样写入，而不是 Unicode 转义
                # indent=2 使 JSON 文件格式化，易于人工阅读
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
                logger.info(f"[Cache Save] 缓存和会话映射已成功写入文件。")

            # 尝试获取保存后文件的大小
            try:
                final_size = os.path.getsize(self.cache_file)
                logger.info(f"[Cache Save] 保存后的文件大小: {final_size} 字节。")
            except OSError:
                # 获取大小失败通常不影响保存结果，记录警告即可
                logger.warning("[Cache Save] 无法获取保存后的文件大小。")

        # 处理保存过程中可能发生的各种异常
        except Exception as e:
            logger.error(f"[Cache Save] 保存缓存文件时发生意外错误: {e}", exc_info=True)
        finally:
             # 记录保存流程结束
             logger.info("[Cache Save] --- 缓存保存流程结束 ---")

    def get_key(self, text, lang, style, file_hash=None):
        """
        根据输入文本、目标语言、翻译风格和可选的文件哈希生成一个唯一的 MD5 缓存键。

        实现原理：
        - 将所有输入参数转换为字符串（处理 None 值）。
        - 将这些字符串用特定格式拼接成一个唯一的源字符串。
        - 对源字符串进行 UTF-8 编码。
        - 计算编码后字符串的 MD5 哈希值。
        - 返回 32 位的十六进制 MD5 哈希字符串。

        参数:
            text (any): 待翻译的原始文本。会被转换为字符串。
            lang (any): 目标语言代码或名称。会被转换为字符串。
            style (any): 翻译风格代码或自定义提示词。会被转换为字符串。
            file_hash (str, optional): 与该文本关联的文件内容的 MD5 哈希值。用于会话隔离。默认为 None。会被转换为字符串。

        返回:
            str: 生成的 32 位十六进制 MD5 缓存键。
        """
        # 将输入转换为字符串，对 None 值转换为空字符串
        text_str = str(text) if text is not None else ''
        lang_str = str(lang) if lang is not None else ''
        style_str = str(style) if style is not None else ''
        hash_str = str(file_hash) if file_hash is not None else ''
        # 构建用于生成哈希的源字符串，包含标识符以区分字段
        key_str = f"text:{text_str}|lang:{lang_str}|style:{style_str}|file_hash:{hash_str}"
        # 计算 UTF-8 编码后字符串的 MD5 哈希值，并获取其十六进制表示
        md5_key = hashlib.md5(key_str.encode("utf-8")).hexdigest()
        # 记录调试日志，显示生成的 Key 和部分文件哈希（如果存在）
        logger.debug(f"生成缓存 Key (MD5): {md5_key} (基于 Text, Lang, Style, FileHash='{hash_str[:8] if hash_str else 'N/A'}...')")
        # 返回计算得到的 MD5 键
        return md5_key

    def get(self, text, lang, style, file_hash=None, log_callback=None):
        """
        尝试从缓存中获取指定条件的翻译结果。

        执行流程：
        1.  调用 `get_key()` 方法生成对应的缓存键。
        2.  使用生成的键尝试在 `self.cache` 字典中查找值。
        3.  如果找到（缓存命中）：
            -   记录命中的日志。
            -   如果提供了 `log_callback` 函数，调用它向 GUI 发送缓存命中的消息。
            -   返回找到的翻译结果 (str)。
        4.  如果未找到（缓存未命中）：
            -   记录未命中的日志。
            -   返回 None。

        参数:
            text (any): 待翻译的原始文本。
            lang (any): 目标语言代码或名称。
            style (any): 翻译风格代码或自定义提示词。
            file_hash (str, optional): 关联的文件哈希。默认为 None。
            log_callback (callable, optional): 一个回调函数，用于将日志消息发送到 GUI。
                                               它应接受两个参数：消息字符串 (str) 和消息类型字符串 (str)。默认为 None。

        返回:
            str or None: 如果缓存命中，返回缓存的翻译结果字符串；否则返回 None。
        """
        # 生成缓存键
        key = self.get_key(text, lang, style, file_hash)
        # 日志前缀，包含部分缓存键以便追踪
        log_prefix = f"[Cache Get][Key: {key[:8]}...]"
        logger.debug(f"{log_prefix} 尝试获取缓存...")
        # 从缓存字典中获取值，如果键不存在，.get() 方法默认返回 None
        translation = self.cache.get(key)

        # 检查是否获取到翻译结果
        if translation:
             # 缓存命中
             logger.info(f"{log_prefix} 缓存命中！")
             # 如果提供了 GUI 日志回调函数
             if log_callback:
                 # --- 修改 GUI 日志消息 ---
                 # 发送更用户友好的缓存命中消息到 GUI
                 log_callback(f"💾 缓存命中，跳过 API 调用 (缓存标识: {key[:8]}...)", "cache")
                 # ----------------------
        else:
            # 缓存未命中
            logger.info(f"{log_prefix} 缓存未命中。")
            # 对于未命中情况，通常不需要通过 log_callback 发送消息，
            # 后续的 API 调用日志会表明需要进行翻译。
        # 返回获取到的结果（命中时为翻译字符串，未命中时为 None）
        return translation

    def set(self, text, lang, style, translation, file_hash=None):
        """
        将翻译结果设置（或更新）到缓存中，并记录与文件哈希的关联关系，最后触发缓存保存到磁盘。

        执行流程：
        1.  调用 `get_key()` 方法生成对应的缓存键。
        2.  检查传入的 `translation` 是否有效（非空、非纯空格的字符串）。如果无效，记录警告并直接返回。
        3.  获取线程锁，确保写入操作的线程安全。
        4.  检查新值是否与缓存中已有的值相同。如果相同，记录调试信息并直接返回，避免不必要的写入和保存。
        5.  将新的翻译结果存入 `self.cache` 字典。
        6.  如果提供了 `file_hash`：
            -   调用内部方法 `_record_session_internal()` 记录文件哈希与缓存键的关联。
        7.  记录缓存设置/更新的日志。
        8.  调用 `save_cache()` 方法将更新后的缓存数据（包括 session_map）保存到磁盘文件。
        9.  释放线程锁（由 `with` 语句自动完成）。

        参数:
            text (any): 原始文本。
            lang (any): 目标语言。
            style (any): 翻译风格或提示词。
            translation (str): 待缓存的翻译结果。
            file_hash (str, optional): 关联的文件哈希。默认为 None。
        """
        # 生成缓存键
        key = self.get_key(text, lang, style, file_hash)
        # 日志前缀
        log_prefix = f"[Cache Set][Key: {key[:8]}...]"
        logger.debug(f"{log_prefix} 尝试设置缓存...")

        # --- 增加对无效翻译结果的检查 ---
        # 确保 translation 是非空、非纯空格的字符串
        if not translation or not isinstance(translation, str) or not translation.strip():
            logger.warning(f"{log_prefix} 尝试设置无效的翻译结果 (空或非字符串)，已忽略。翻译结果: '{translation}'")
            return # 不缓存无效结果

        # 获取线程锁，保护缓存写入操作
        with self.lock:
            # --- 优化：检查新值是否与旧值相同 ---
            if self.cache.get(key) == translation:
                 logger.debug(f"{log_prefix} 新值与缓存中现有值相同，跳过设置和保存。")
                 return # 值未改变，无需操作

            # 将翻译结果存入缓存字典
            self.cache[key] = translation
            logger.info(f"{log_prefix} 缓存条目已设置/更新。")
            # 记录关联的文件哈希信息（部分）
            logger.debug(f"{log_prefix} FileHash: {file_hash[:8] if file_hash else 'N/A'}")

            # 如果提供了文件哈希，则记录会话关联
            if file_hash is not None:
                # 调用内部方法记录关联关系（此时已持有锁）
                self._record_session_internal(file_hash, key)
            else:
                # 未提供文件哈希，不记录会话关联
                logger.debug(f"{log_prefix} 未提供 FileHash，不记录会话关联。")

            # 触发缓存保存操作
            logger.debug(f"{log_prefix} 触发缓存保存...")
            self.save_cache() # save_cache 内部有日志记录保存过程
            logger.debug(f"{log_prefix} 缓存保存已触发。")
        # 锁在 with 语句结束时自动释放

    def _record_session_internal(self, file_hash, cache_key):
        """
        内部方法，用于记录缓存键 (`cache_key`) 与特定文件哈希 (`file_hash`) 之间的关联关系。
        这个方法被设计为在持有线程锁 (`self.lock`) 的上下文中调用。

        执行流程：
        1.  检查 `file_hash` 是否已作为键存在于 `self.session_map` 字典中。
        2.  如果 `file_hash` 不存在：
            -   在 `self.session_map` 中为该 `file_hash` 创建一个新的空列表。
            -   记录日志，说明这是首次遇到该文件哈希。
        3.  检查 `cache_key` 是否已存在于与 `file_hash` 关联的列表中。
        4.  如果 `cache_key` 不在列表中：
            -   将 `cache_key` 添加到该列表中。
            -   记录日志，说明已将新的缓存键关联到此文件哈希。
        5.  如果 `cache_key` 已在列表中：
            -   记录调试日志，说明无需重复添加。

        参数:
            file_hash (str): 文件内容的 MD5 哈希值。
            cache_key (str): 与该文件相关的翻译缓存键。
        """
        # 日志前缀，包含部分哈希和键
        log_prefix = f"[Session Record][Hash: {file_hash[:8]}...][Key: {cache_key[:8]}...]"
        logger.debug(f"{log_prefix} 尝试记录会话映射...")
        # 检查 session_map 中是否已有该文件哈希的条目
        if file_hash not in self.session_map:
            # 如果是第一次遇到这个文件哈希，为其创建一个空列表
            self.session_map[file_hash] = []
            logger.debug(f"{log_prefix} 文件哈希首次出现，创建新的会话映射列表。")
        # 检查当前缓存键是否已经与这个文件哈希关联
        if cache_key not in self.session_map[file_hash]:
            # 如果尚未关联，将缓存键添加到列表中
            self.session_map[file_hash].append(cache_key)
            logger.info(f"{log_prefix} 新的缓存键已关联到此文件哈希。")
        else:
            # 如果已经关联，则无需操作
            logger.debug(f"{log_prefix} 缓存键已存在于此文件哈希的映射中，无需重复添加。")

    def purge_session_cache(self, file_hash):
        """
        清除与指定文件哈希 (`file_hash`) 相关联的所有缓存条目。

        执行流程：
        1.  获取线程锁，确保操作的线程安全。
        2.  检查 `file_hash` 是否存在于 `self.session_map` 中。
        3.  如果存在：
            -   获取与该 `file_hash` 关联的所有缓存键列表（创建副本以安全迭代）。
            -   遍历这个列表中的每个缓存键 (`key`)：
                -   检查 `key` 是否仍然存在于 `self.cache` 字典中。
                -   如果存在，从 `self.cache` 中删除该条目，并增加删除计数。
                -   如果不存在，记录警告（可能已被其他操作清除）。
            -   从 `self.session_map` 中删除该 `file_hash` 条目（无论关联的缓存键是否实际被删除）。
            -   如果 `self.cache` 或 `self.session_map` 被修改，调用 `save_cache()` 保存更改。
            -   记录清除操作的摘要日志（删除了多少条目）。
        4.  如果 `file_hash` 不存在于 `self.session_map` 中：
            -   记录日志，说明无需清除。
        5.  释放线程锁。
        6.  记录清除流程结束的日志。

        参数:
            file_hash (str): 需要清除缓存的文件内容的 MD5 哈希值。
        """
        # 日志前缀
        log_prefix = f"[Cache Purge][Hash: {file_hash[:8]}...]"
        logger.info(f"{log_prefix} --- 开始清除会话关联缓存 ---")
        # 初始化计数器和标志
        keys_deleted_count = 0
        session_map_modified = False
        cache_modified = False

        # 获取线程锁
        with self.lock:
            # 检查 session_map 中是否存在该文件哈希
            if file_hash in self.session_map:
                # 获取与该文件哈希关联的所有缓存键列表
                # 创建列表副本 list() 以允许在迭代时安全地修改原始数据（尽管这里是删除 session_map[file_hash] 本身）
                keys_to_delete = list(self.session_map[file_hash])
                logger.info(f"{log_prefix} 在会话映射中找到记录，准备清除 {len(keys_to_delete)} 个关联的缓存键...")

                # 遍历要删除的缓存键
                for key in keys_to_delete:
                    # 检查这个缓存键是否真的还在主缓存字典中
                    if key in self.cache:
                        # 如果在，从主缓存中删除
                        del self.cache[key]
                        keys_deleted_count += 1 # 增加删除计数
                        cache_modified = True # 标记缓存已被修改
                        logger.debug(f"{log_prefix}   - 已成功删除缓存键: {key[:8]}...")
                    else:
                        # 如果不在，记录警告，可能已被其他操作（如 clear_all_cache）清除
                        logger.warning(f"{log_prefix}   - 尝试删除缓存键 {key[:8]}... 但未在缓存中找到。可能已被其他操作清除。")

                # 从会话映射中移除该文件哈希的条目
                # 无论关联的键是否在 cache 中找到，都应该移除映射关系
                del self.session_map[file_hash]
                session_map_modified = True # 标记会话映射已被修改
                logger.info(f"{log_prefix} 已成功删除文件哈希 '{file_hash[:8]}...' 的会话映射条目。")

                # 如果缓存或会话映射有任何更改，则需要保存
                if cache_modified or session_map_modified:
                    logger.info(f"{log_prefix} 检测到缓存或会话映射已更改，触发保存...")
                    self.save_cache() # 保存更改到磁盘
                    logger.info(f"{log_prefix} 缓存清除操作已完成并保存。共删除 {keys_deleted_count} 个缓存条目。")
                else:
                    # 如果 session_map 存在但 cache 中没有对应的 key，或者 session_map 本身没有被修改（理论上不可能到这里）
                    logger.info(f"{log_prefix} 会话映射中存在记录，但未找到实际关联的缓存条目或未修改会话映射，无需保存更改。")

            # 如果 session_map 中不存在该文件哈希
            else:
                logger.info(f"{log_prefix} 在会话映射中未找到该文件哈希 '{file_hash[:8]}...'，无需清除缓存。")
        # 锁在 with 语句结束时自动释放
        logger.info(f"{log_prefix} --- 会话关联缓存清除流程结束 ---")

    def clear_all_cache(self):
        """
        清空内存中的所有缓存数据 (`self.cache` 和 `self.session_map`)，
        并尝试清空（覆盖）磁盘上的缓存文件。

        执行流程：
        1.  获取线程锁。
        2.  记录当前缓存和会话映射的数量。
        3.  如果缓存和会话映射都已为空：
            -   记录日志说明无需清空内存。
            -   如果缓存文件存在，则继续执行文件清空操作（确保文件也被清空）。
            -   如果文件也不存在，则直接结束。
        4.  如果内存中有数据，则清空 `self.cache` 和 `self.session_map` 字典。
        5.  记录内存清空的日志。
        6.  尝试清空磁盘上的缓存文件：
            -   获取缓存文件所在目录。
            -   如果目录不存在，尝试创建。如果创建失败，记录错误但继续尝试写入文件（可能路径是当前目录）。
            -   以写入模式 ('w') 打开缓存文件。
            -   将一个空的 JSON 结构 (`{"cache": {}, "session_map": {}}`) 写入文件，这会覆盖原有内容或创建一个空文件。
            -   记录文件清空成功的日志。
        7.  处理清空文件时可能发生的异常，并记录错误日志。
        8.  释放线程锁。
        9.  记录整个清空流程结束的日志。
        """
        logger.info("[Cache Clear All] --- 开始清空所有缓存数据 ---")
        # 获取线程锁
        with self.lock:
            # 获取当前缓存和会话映射的数量
            original_cache_count = len(self.cache)
            original_session_count = len(self.session_map)
            logger.info(f"[Cache Clear All] 当前状态: {original_cache_count} 个缓存条目, {original_session_count} 个会话映射。")

            # 检查内存中的缓存是否已经为空
            if original_cache_count == 0 and original_session_count == 0:
                logger.info("[Cache Clear All] 缓存和会话映射已为空，无需执行内存清空操作。")
                # 即使内存为空，也要检查文件是否存在，并尝试清空文件
                if os.path.exists(self.cache_file):
                     logger.info(f"[Cache Clear All] 缓存文件存在，尝试清空文件内容: {self.cache_file}")
                     # 继续执行下面的文件清空逻辑
                else:
                     # 如果文件也不存在，则确实无需任何操作
                     logger.info("[Cache Clear All] 缓存文件也不存在。")
                     logger.info("[Cache Clear All] --- 清空所有缓存数据流程结束 (无需操作) ---")
                     return # 既然内存和文件都为空，直接返回

            # 清空内存中的字典
            self.cache.clear()
            self.session_map.clear()
            logger.info("[Cache Clear All] 内存中的缓存和会话映射已清空。")

            # --- 尝试清空或创建空的缓存文件 ---
            logger.info(f"[Cache Clear All] 尝试清空缓存文件: {self.cache_file}")
            try:
                # 获取缓存文件所在目录
                cache_dir = os.path.dirname(self.cache_file)
                # 如果目录路径非空且不存在
                if cache_dir and not os.path.exists(cache_dir):
                    logger.info(f"[Cache Clear All] 缓存目录不存在，尝试创建: {cache_dir}")
                    try:
                        os.makedirs(cache_dir)
                        logger.info(f"[Cache Clear All] 缓存目录创建成功: {cache_dir}")
                    except OSError as dir_err:
                        # 即使目录创建失败，也记录错误并继续尝试写入文件（可能路径就是当前目录）
                        logger.error(f"[Cache Clear All] 无法创建缓存目录 '{cache_dir}': {dir_err}", exc_info=True)
                        pass # 继续执行写入

                # 定义空的缓存数据结构
                empty_data = {"cache": {}, "session_map": {}}
                # 以写入模式打开文件，覆盖或创建
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    # 将空结构写入文件
                    json.dump(empty_data, f, indent=2)
                logger.info(f"[Cache Clear All] 成功清空并覆盖/创建了缓存文件。")
                # 记录操作前的状态以供对比
                logger.info(f"[Cache Clear All] 操作前缓存条目数: {original_cache_count}, 会话映射数: {original_session_count}")

            # 处理清空文件时发生的异常
            except Exception as e:
                logger.error(f"[Cache Clear All] 清空缓存文件时发生错误: {e}", exc_info=True)
            finally:
                # 记录整个清空流程结束
                logger.info("[Cache Clear All] --- 清空所有缓存数据流程结束 ---")
        # 锁在 with 语句结束时自动释放