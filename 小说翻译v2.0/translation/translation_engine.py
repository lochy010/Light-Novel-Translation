# translation/translation_engine.py
"""
翻译引擎核心模块 (translation_engine.py)

功能：
该模块封装了与翻译服务 API（在此特指 DeepSeek API）交互的核心逻辑。它负责构建请求、
调用 API、处理响应、管理翻译上下文、集成缓存机制以及实现错误处理和重试策略。

核心机制：
- 使用 `openai` 库（适配 DeepSeek API）与翻译服务进行通信。
- 实现 `translate_with_context` 方法，支持基于前文摘要的上下文关联翻译。
- 提供 `safe_translate` 方法作为外部调用的主要接口，该方法封装了重试逻辑、
  模型降级（可选）、暂停检查以及更健壮的错误处理。
- 包含 `test_api_connection` 方法，用于测试与 API 服务器的连通性和密钥有效性。
- 集成 `cache_manager`，在进行 API 调用前检查缓存，并将成功结果存入缓存。
- 实现简单的格式保留与恢复机制 (`preserve_formatting`, `restore_formatting`)，
  尝试保护原文中的 Markdown 链接、代码块等在翻译过程中不被破坏。
- 根据用户选择的语言、风格（或自定义提示词）、模型和温度参数，动态构建发送给 API 的 Prompt。
- 清理 API 返回的原始文本，去除可能的前缀和多余空白。
- 记录详细的操作日志，便于追踪翻译流程和调试问题。
"""

# 导入 logging 模块，用于记录程序运行时的信息、警告和错误。
import logging
# 导入 time 模块，用于计算 API 调用耗时和实现重试等待。
import time
# 导入 re 模块，用于正则表达式操作，主要在清理 API 结果时使用。
import re
# 导入 uuid 模块，用于生成唯一的标识符，在格式保留中创建占位符。
import uuid

# 从 openai 库导入所需的类和特定的异常类型
# OpenAI: 用于创建 API 客户端实例。
# APITimeoutError: 表示 API 请求超时。
# APIConnectionError: 表示无法连接到 API 服务器。
# RateLimitError: 表示达到 API 请求频率限制 (HTTP 429)。
# APIStatusError: 表示 API 返回了非 2xx 的状态码，包含具体的 status_code 和 message。
# AuthenticationError: 表示 API 密钥无效或权限不足 (HTTP 401)。
# BadRequestError: 表示请求本身有问题，如格式错误或参数无效 (HTTP 400, 422)。
# InternalServerError: 表示 API 服务器内部错误 (HTTP 5xx)。
from openai import (
    OpenAI, APITimeoutError, APIConnectionError, RateLimitError, APIStatusError,
    AuthenticationError, BadRequestError, InternalServerError
)
# 导入配置文件中的翻译、提示词和 API 相关设置
# settings 模块包含了应用程序所需的各种配置常量。
from config.settings import TRANSLATION_CONFIG, PROMPT_CONFIG, API_CONFIG

# --- 初始化模块级日志记录器 ---
# 获取一个名为 'translation_engine' 的日志记录器实例。
# 日志的格式化将在主程序入口 (main.py) 中统一设置。
logger = logging.getLogger(__name__) # 使用当前模块名作为记录器名称

# --- 翻译引擎核心类 ---
class TranslationEngine:
    """
    封装翻译核心功能的类。

    负责与 DeepSeek API 交互，管理翻译流程，包括上下文处理、缓存集成、
    错误处理和 API 调用。

    属性:
        client (OpenAI): 用于与 DeepSeek API 通信的客户端实例。
        cache (TranslationCache): 缓存管理器的实例，用于存储和检索翻译结果。
        language_map (dict): 将用户界面语言名称映射到 API 使用的语言代码。
        style_map (dict): 将用户界面风格名称映射到内部代码或标识符。
        model_map (dict): 将用户界面模型名称映射到 API 使用的模型 ID。
        gui (TranslationGUI, optional): 对 GUI 主窗口实例的引用，允许引擎访问界面状态（如自定义提示词），
                                        由外部（如 main.py）在初始化后设置。默认为 None。
    """

    def __init__(self, api_key, cache_manager):
        """
        初始化 TranslationEngine 实例。

        - 创建 OpenAI 客户端，配置 API Key、Base URL 和 Timeout。
        - 设置传入的缓存管理器实例。
        - 从配置文件加载语言、风格和模型映射。
        - 记录初始化过程的日志。

        参数:
            api_key (str): 用于访问 DeepSeek API 的密钥。
            cache_manager (TranslationCache): 外部传入的缓存管理器实例。

        异常:
            ConnectionError: 如果在创建 OpenAI 客户端时发生错误（例如网络问题、配置错误）。
        """
        self.gui = None # 初始化 gui 属性为 None，等待外部设置
        logger.info("--- TranslationEngine 初始化开始 ---")
        logger.info("初始化 OpenAI 客户端...")
        try:
            # 从配置中读取 API Base URL 和 Timeout
            base_url = API_CONFIG.get("BASE_URL", "https://api.deepseek.com")
            timeout = API_CONFIG.get("TIMEOUT", 180)
            logger.debug(f"使用 API Base URL: {base_url}")
            logger.debug(f"使用 API Timeout: {timeout} 秒")
            # 创建 OpenAI 客户端实例，适配 DeepSeek API
            self.client = OpenAI(
                api_key=api_key,      # 设置 API 密钥
                base_url=base_url,    # 设置 API 端点
                timeout=timeout,      # 设置请求超时时间
            )
            logger.info("OpenAI 客户端实例创建成功。")
        except Exception as e:
            # 如果客户端初始化失败，记录关键错误并抛出异常
            logger.critical(f"OpenAI 客户端初始化失败: {e}", exc_info=True)
            raise ConnectionError(f"无法初始化翻译引擎客户端: {e}")

        # 设置缓存管理器实例
        logger.info("设置缓存管理器...")
        self.cache = cache_manager
        logger.info("缓存管理器设置完成。")

        # 加载翻译相关的配置映射
        logger.info("加载翻译配置...")
        self.language_map = TRANSLATION_CONFIG["LANGUAGE_MAP"]
        self.style_map = TRANSLATION_CONFIG["STYLE_MAP"]
        self.model_map = TRANSLATION_CONFIG["MODEL_MAP"]
        logger.info("翻译相关配置（语言、风格、模型映射）加载完成。")
        # 记录加载的配置信息（用于调试）
        logger.debug(f"支持的目标语言: {list(self.language_map.keys())}")
        logger.debug(f"支持的翻译风格: {list(self.style_map.keys())}")
        logger.debug(f"支持的模型: {list(self.model_map.keys())}")
        logger.info("--- TranslationEngine 初始化完成 ---")

    def test_api_connection(self):
        """
        测试与 DeepSeek API 服务器的连通性，并验证提供的 API 密钥是否有效。

        实现方式：
        - 调用一个低成本、通常可用的 API 端点，例如 `client.models.list()`。
        - 捕获可能发生的各种 `openai` 库定义的异常，并根据异常类型生成用户友好的反馈信息。
        - 计算 API 调用的延迟。

        返回:
            tuple[bool, str]: 一个包含两个元素的元组：
                - bool: True 表示连接成功且密钥有效，False 表示失败。
                - str: 描述测试结果或错误原因的消息文本。
        """
        logger.info("[API 测试] 开始测试 API 连接和密钥验证...")
        try:
            logger.debug("[API 测试] 尝试调用 client.models.list()...")
            start_time = time.time()
            # 调用 models.list() 端点，这个调用通常用于获取可用模型列表
            # 这里我们只关心调用是否成功，不关心返回的具体内容
            self.client.models.list()
            # 计算调用耗时
            latency = time.time() - start_time
            logger.info(f"[API 测试] API 连接成功，密钥有效。测试调用耗时: {latency:.3f} 秒。")
            # 返回成功状态和消息
            return True, f"✅ API 连接成功，密钥有效 (耗时: {latency:.2f}秒)。"

        # --- 异常处理块 ---
        # 捕获特定的 OpenAI 异常类型，提供更具体的错误信息
        except AuthenticationError as e: # HTTP 401
            error_msg = f"认证失败 (401): {e}. 请检查您的 API Key 是否正确或具有有效权限。"
            logger.error(f"[API 测试] {error_msg}", exc_info=False) # 通常不需要堆栈信息
            return False, f"❌ API 测试失败: {error_msg}"
        except RateLimitError as e: # HTTP 429
            error_msg = f"请求速率达到上限 (429): {e}. 请稍后重试或降低请求频率。"
            logger.error(f"[API 测试] {error_msg}", exc_info=False)
            return False, f"❌ API 测试失败: {error_msg}"
        except BadRequestError as e: # HTTP 400, 422 等
            status_code = e.status_code if hasattr(e, 'status_code') else 400
            error_detail = str(e)
            if status_code == 400: error_msg = f"请求格式错误 (400): {error_detail}. 请检查请求体。"
            elif status_code == 422: error_msg = f"请求参数错误 (422): {error_detail}. 请检查请求中的参数是否符合API要求。"
            else: error_msg = f"无效的 API 请求 ({status_code}): {error_detail}"
            logger.error(f"[API 测试] {error_msg}", exc_info=False)
            return False, f"❌ API 测试失败: {error_msg}"
        except InternalServerError as e: # HTTP 5xx
            status_code = e.status_code if hasattr(e, 'status_code') else 500
            error_detail = str(e)
            if status_code == 503: error_msg = f"服务器繁忙 (503): {error_detail}. 服务器当前负载过高，请稍后重试。"
            else: error_msg = f"服务器内部故障 ({status_code}): {error_detail}. 服务器内部发生错误，请稍后重试或联系支持。"
            logger.error(f"[API 测试] {error_msg}", exc_info=False)
            return False, f"❌ API 测试失败: {error_msg}"
        except APIStatusError as e: # 其他非 2xx 状态码，如 402 (余额不足)
            status_code = e.status_code
            error_detail = e.message # 获取错误消息
            logger.error(f"[API 测试] API 状态错误 (代码: {status_code}): {error_detail}", exc_info=False)
            if status_code == 402: error_msg = f"余额不足 (402): {error_detail}. 请检查您的账户余额并充值。"
            else: error_msg = f"API 返回状态错误 (代码: {status_code}): {error_detail}"
            return False, f"❌ API 测试失败: {error_msg}"
        except APITimeoutError as e: # 请求超时
            timeout_value = self.client.timeout.read if hasattr(self.client.timeout, 'read') else 'N/A'
            error_msg = f"请求超时 (>{timeout_value}秒): {e}. 请检查网络连接或增加超时设置。"
            logger.error(f"[API 测试] {error_msg}", exc_info=False)
            return False, f"❌ API 测试失败: {error_msg}"
        except APIConnectionError as e: # 连接错误
            api_endpoint = self.client.base_url
            error_msg = f"连接错误: {e}. 无法连接到 API 服务 ({api_endpoint})，请检查网络或服务端点。"
            logger.error(f"[API 测试] {error_msg}", exc_info=False)
            return False, f"❌ API 测试失败: {error_msg}"
        except Exception as e: # 捕获其他所有未预期错误
            error_msg = f"发生未预期错误: {e}"
            logger.error(f"[API 测试] {error_msg}", exc_info=True) # 记录堆栈信息
            return False, f"❌ API 测试失败 (未知错误): {error_msg} 请查看日志了解详情。"

    def translate_with_context(self, text, target_lang_code, style_code_or_prompt, temperature, model_name, file_hash,
                               previous_chunk="",
                               log_callback=None):
        """
        执行单次翻译（带上下文）的核心方法。它处理缓存检查、Prompt 构建、API 调用和结果处理。
        通常由 `safe_translate` 方法调用。

        参数:
            text (str): 需要翻译的文本块。
            target_lang_code (str): 目标语言的代码 (例如 'zh', 'en')。
            style_code_or_prompt (str): 预设的翻译风格代码 (例如 'standard') 或用户提供的自定义提示词字符串。
            temperature (float): API 调用时使用的温度参数，控制生成文本的随机性。
            model_name (str): 用户在界面上选择的模型名称 (例如 'DeepSeek-V3')。
            file_hash (str): 当前处理文件的 MD5 哈希值，用于缓存键生成和日志关联。
            previous_chunk (str, optional): 上一个已处理文本块的末尾部分，用于构建上下文。默认为空字符串。
            log_callback (callable, optional): 一个回调函数，用于将日志消息发送到 GUI。
                                               它应接受两个参数：消息字符串 (str) 和消息类型字符串 (str)。默认为 None。

        返回:
            str: 翻译后的文本结果。如果发生错误，会抛出异常。

        异常:
            TimeoutError: API 请求超时。
            ConnectionError: 无法连接到 API 服务器或服务器内部错误 (5xx)。
            PermissionError: API 认证失败 (401)、速率限制 (429) 或余额不足 (402)。
            ValueError: API 请求格式错误 (400/422)、无效的模型名称或 API 返回无效响应。
            Exception: 其他所有未预期的错误。
        """
        # --- 日志和初始化 ---
        # 使用文件哈希前缀，方便在日志中追踪特定文件的处理过程
        log_prefix = f"[FileHash: {file_hash[:8]}...]" if file_hash else "[No FileHash]"
        logger.info(f"{log_prefix} --- 开始翻译块处理 ---")
        logger.info(f"{log_prefix} 目标语言: {target_lang_code}, 模型: {model_name}, 温度: {temperature}")
        # 记录使用的风格信息
        if style_code_or_prompt in self.style_map.values():
            # 如果是预设风格，查找对应的名称
            style_display_name = next((name for name, code in self.style_map.items() if code == style_code_or_prompt),
                                      style_code_or_prompt) # 找不到则用代码本身
            logger.info(f"{log_prefix} 使用预设风格: {style_display_name} ({style_code_or_prompt})")
        else:
            # 如果是自定义提示词，记录片段（完整提示词在后面记录）
            prompt_snippet = style_code_or_prompt[:50] + ('...' if len(style_code_or_prompt) > 50 else '')
            logger.info(f"{log_prefix} 使用自定义提示词 (片段): '{prompt_snippet}'")

        # --- 格式保留预处理 ---
        logger.info(f"{log_prefix} 执行格式保留预处理...")
        # 调用 preserve_formatting 处理文本，获取处理后的文本和替换项字典
        processed_text, replacements = self.preserve_formatting(text, target_lang_code) # 函数内部有日志

        # --- 缓存检查 ---
        logger.info(f"{log_prefix} 检查翻译缓存...")
        # 生成缓存键
        cache_key = self.cache.get_key(text, target_lang_code, style_code_or_prompt, file_hash)
        logger.debug(f"{log_prefix} 生成缓存 Key: {cache_key}")
        # 尝试从缓存获取结果，并将 log_callback 传递给 get 方法
        # get 方法内部会处理缓存命中/未命中的日志，并调用 log_callback 通知 GUI
        cached_result = self.cache.get(
                text, target_lang_code, style_code_or_prompt, file_hash,
                log_callback=log_callback
        )
        # 如果获取到缓存结果
        if cached_result:
            logger.info(f"{log_prefix} 缓存命中。")
            # --- 恢复格式 ---
            logger.info(f"{log_prefix} 从缓存恢复格式...")
            # 对缓存结果应用格式恢复
            restored_result = self.restore_formatting(cached_result, replacements, target_lang_code) # 函数内部有日志
            logger.info(f"{log_prefix} --- 翻译块处理完成 (来自缓存) ---")
            # 返回恢复格式后的结果
            return restored_result

        # --- 如果缓存未命中 ---
        logger.info(f"{log_prefix} 缓存未命中，继续执行 API 翻译流程。")
        # --- 构建上下文 ---
        logger.info(f"{log_prefix} 构建翻译上下文...")
        # 基于上一个块的内容构建上下文摘要
        context = self._build_context(previous_chunk, target_lang_code) # 函数内部有日志

        # --- 确定 API 模型 ID ---
        logger.info(f"{log_prefix} 确定 API 模型 ID...")
        # 从 model_map 中查找用户选择的模型名称对应的 API ID
        api_model_id = self.model_map.get(model_name)
        # 如果找不到，说明配置或用户选择有问题，抛出 ValueError
        if not api_model_id:
            error_msg = f"无效的模型名称: '{model_name}'。在配置中找不到对应的 API ID。"
            logger.error(f"{log_prefix} {error_msg}")
            raise ValueError(error_msg)
        logger.info(f"{log_prefix} 选定 API 模型 ID: {api_model_id} (对应用户选择: {model_name})")

        # --- 构建最终 API Prompt ---
        logger.info(f"{log_prefix} 构建最终 API Prompt...")
        # 组合上下文、指令模板和处理后的文本，生成最终发送给 API 的 Prompt
        full_prompt = self._build_prompt(target_lang_code, style_code_or_prompt, context, processed_text) # 函数内部有日志

        # --- 记录完整 Prompt ---
        prompt_length = len(full_prompt)
        logger.info(f"{log_prefix} Prompt 构建完成，总长度: {prompt_length} 字符。")
        # 使用 INFO 级别记录完整的 Prompt 内容，便于调试
        logger.info(
            f"{log_prefix} 完整发送的 Prompt:\n------ START PROMPT ------\n{full_prompt}\n------ END PROMPT ------")

        # --- 调用 API ---
        logger.info(f"{log_prefix} 调用 DeepSeek API...")
        # --- 发送 GUI 日志：提示正在调用 API ---
        if log_callback:
            log_callback("📞 正在调用翻译 API...", "info")
        # --- 结束 GUI 日志 ---
        try:
            start_time = time.time()
            logger.debug(f"{log_prefix} 发起 client.chat.completions.create 请求...")
            # 调用 OpenAI 客户端的 chat completions 接口
            response = self.client.chat.completions.create(
                model=api_model_id,             # 指定使用的模型 ID
                messages=[{"role": "user", "content": full_prompt}], # 构建消息列表
                temperature=float(temperature), # 设置温度
                max_tokens=8192,                # 设置最大生成 token 数（可调整）
            )
            # 计算 API 调用耗时
            api_latency = time.time() - start_time
            logger.info(f"{log_prefix} API 调用成功，耗时: {api_latency:.3f} 秒。")
            # --- 发送 GUI 日志：API 调用成功 ---
            if log_callback:
                log_callback(f"✅ API 调用成功 (耗时: {api_latency:.2f}s)，正在处理结果...", "success")
            # --- 结束 GUI 日志 ---

            # --- 处理 API 响应 ---
            logger.info(f"{log_prefix} 处理 API 响应并缓存结果...")
            # 调用内部方法处理响应，提取文本，记录 token 使用量等
            raw_result = self._process_api_response(response, api_latency, model_name, log_prefix) # 函数内部有日志

            # --- 缓存结果 ---
            # 将原始文本、参数和获取到的翻译结果存入缓存
            # cache.set 方法内部会处理日志记录和文件保存
            self.cache.set(text, target_lang_code, style_code_or_prompt, raw_result, file_hash)

            # --- 恢复格式并返回 ---
            logger.info(f"{log_prefix} 对 API 结果恢复格式...")
            restored_result = self.restore_formatting(raw_result, replacements, target_lang_code) # 函数内部有日志
            logger.info(f"{log_prefix} --- 翻译块处理完成 (通过 API) ---")
            # 返回最终结果
            return restored_result

        # --- 精细化的异常处理 ---
        # 捕获特定异常类型，提供更明确的错误信息和处理逻辑
        except APITimeoutError as e: # 超时错误
            timeout_value = self.client.timeout.read if hasattr(self.client.timeout, 'read') else 'N/A'
            error_msg = f"API 调用超时 (>{timeout_value}秒): {e}"
            logger.error(f"{log_prefix} {error_msg}", exc_info=False) # 无需完整堆栈
            # 抛出 TimeoutError，safe_translate 会捕获并尝试重试
            raise TimeoutError(error_msg) from e

        except AuthenticationError as e: # 认证错误 (401)
            error_msg = f"API 认证失败 (401): {e}. 请检查 API Key 配置。"
            logger.critical(f"{log_prefix} {error_msg}", exc_info=False) # 这是关键错误
            # 抛出 PermissionError，safe_translate 会捕获并标记为不可重试
            raise PermissionError(error_msg) from e

        except RateLimitError as e: # 速率限制错误 (429)
            error_msg = f"API 速率限制 (429): {e}. 请求过于频繁。"
            logger.error(f"{log_prefix} {error_msg}", exc_info=False)
            # 抛出 PermissionError，safe_translate 会捕获并标记为不可重试
            raise PermissionError(error_msg) from e

        except BadRequestError as e: # 请求错误 (400/422)
            status_code = e.status_code if hasattr(e, 'status_code') else 400
            error_detail = str(e)
            if status_code == 400: error_msg = f"API 请求格式错误 (400): {error_detail}。"
            elif status_code == 422: error_msg = f"API 请求参数错误 (422): {error_detail}。"
            else: error_msg = f"无效的 API 请求 ({status_code}): {error_detail}"
            logger.error(f"{log_prefix} {error_msg}", exc_info=False)
            # 抛出 ValueError，safe_translate 会捕获并标记为不可重试
            raise ValueError(error_msg) from e

        except InternalServerError as e: # 服务器内部错误 (5xx)
            status_code = e.status_code if hasattr(e, 'status_code') else 500
            error_detail = str(e)
            if status_code == 503: error_msg = f"API 服务器繁忙 (503): {error_detail}。"
            else: error_msg = f"API 服务器内部故障 ({status_code}): {error_detail}。"
            logger.error(f"{log_prefix} {error_msg}", exc_info=False)
            # 抛出 ConnectionError，safe_translate 会捕获并尝试重试
            raise ConnectionError(error_msg) from e

        except APIStatusError as e: # 其他非 2xx 错误 (如 402)
            status_code = e.status_code
            error_detail = e.message
            # 根据状态码细化错误类型和处理方式
            if status_code == 401: # 再次捕获 401
                error_msg = f"API 认证失败 ({status_code}): {error_detail}"
                logger.critical(f"{log_prefix} {error_msg}", exc_info=False)
                raise PermissionError(error_msg) from e
            elif status_code == 402: # 余额不足
                error_msg = f"账户余额不足 (402): {error_detail}。"
                logger.error(f"{log_prefix} {error_msg}", exc_info=False)
                raise PermissionError(error_msg) from e # 归类为权限/配额问题，不可重试
            elif status_code == 429: # 再次捕获 429
                error_msg = f"请求速率过快 (429): {error_detail}"
                logger.error(f"{log_prefix} {error_msg}", exc_info=False)
                raise PermissionError(error_msg) from e
            elif status_code == 400 or status_code == 422: # 再次捕获 400/422
                error_msg = f"API 请求无效 ({status_code}): {error_detail}"
                logger.error(f"{log_prefix} {error_msg}", exc_info=False)
                raise ValueError(error_msg) from e
            elif status_code >= 500: # 再次捕获 5xx
                error_msg = f"翻译服务错误 ({status_code}): {error_detail}"
                logger.error(f"{log_prefix} {error_msg}", exc_info=False)
                raise ConnectionError(error_msg) from e # 服务器错误，可重试
            else: # 其他未知状态码
                error_msg = f"未知的 API 状态错误 ({status_code}): {error_detail}"
                logger.error(f"{log_prefix} {error_msg}", exc_info=True) # 记录堆栈
                raise Exception(error_msg) from e # 抛出通用异常

        except APIConnectionError as e: # 连接错误
            error_msg = f"无法连接到翻译服务: {e}"
            logger.error(f"{log_prefix} {error_msg}", exc_info=False)
            # 抛出 ConnectionError，safe_translate 会捕获并尝试重试
            raise ConnectionError(error_msg) from e

        except Exception as e: # 捕获所有其他未预料的错误
            error_msg = f"API 调用时发生未预期错误: {e}"
            logger.error(f"{log_prefix} {error_msg}", exc_info=True) # 记录完整堆栈
            # 抛出通用异常，safe_translate 会捕获并标记为失败
            raise Exception(f"翻译 API 调用失败: {str(e)}") from e

    def _build_context(self, previous_chunk, target_lang_code):
        """
        根据上一个翻译块的内容构建上下文摘要。

        参数:
            previous_chunk (str): 上一个已处理文本块的原始文本（或其末尾部分）。
            target_lang_code (str): 目标语言代码，用于从配置中获取上下文长度限制。

        返回:
            str: 包含 "前文摘要：" 前缀的上下文文本，如果 `previous_chunk` 为空则返回空字符串。
        """
        # 如果上一个块为空，则不构建上下文
        if not previous_chunk:
            logger.debug("前一个块为空，不构建上下文。")
            return ""
        # 从配置中获取该语言的最大上下文长度，提供默认值
        max_context_length = TRANSLATION_CONFIG["CONTEXT_LENGTH"].get(target_lang_code, 200)
        logger.debug(f"根据目标语言 '{target_lang_code}'，最大上下文长度设置为: {max_context_length} 字符。")
        # 从上一个块的末尾截取指定长度的文本作为上下文
        context_text = previous_chunk[-max_context_length:]
        # 记录构建的上下文摘要（部分内容）
        logger.debug(f"构建的上下文摘要 (取自前块末尾): '{context_text[:50].replace(chr(10), '')}...'(实际长度: {len(context_text)})")
        # 返回带前缀的上下文字符串
        return f"前文摘要：{context_text}\n\n"

    def _build_prompt(self, target_lang_code, style_code_or_prompt, context, processed_text):
        """
        根据目标语言、风格/自定义提示词、上下文和待翻译文本，构建最终发送给 API 的完整 Prompt。

        参数:
            target_lang_code (str): 目标语言代码。
            style_code_or_prompt (str): 预设风格代码或自定义提示词。
            context (str): 由 `_build_context` 生成的上下文摘要。
            processed_text (str): 经过格式保留预处理后的待翻译文本。

        返回:
            str: 组合好的、可以直接发送给 API 的完整 Prompt 字符串。
        """
        # 获取目标语言的显示名称（用于提示词）
        lang_name = next((name for name, code in self.language_map.items() if code == target_lang_code), target_lang_code)
        logger.debug(f"开始为目标语言 '{lang_name}' ({target_lang_code}) 构建 Prompt 模板...")
        # 判断是使用预设风格还是自定义提示词
        is_preset_style = style_code_or_prompt in self.style_map.values()

        final_prompt_template = "" # 初始化最终的指令模板部分
        # --- 处理自定义提示词 ---
        if not is_preset_style:
            custom_prompt = style_code_or_prompt # 自定义提示词就是传入的字符串
            logger.debug("检测到使用自定义提示词。")
            # 基础要求，确保输出的是目标语言且仅包含翻译文本
            base_requirement = f"请严格使用{lang_name}进行翻译，并按照以下要求翻译，仅输出翻译后的文本：\n"
            # 如果用户提供了自定义提示词
            if custom_prompt:
                # 检查用户的提示词是否已包含关键的输出指令
                if "仅输出翻译后的文本" not in custom_prompt:
                     # 如果没有，将基础要求加在用户提示词之前
                     final_prompt_template = f"{base_requirement}{custom_prompt}"
                     logger.debug("自定义提示词未包含输出指令，已自动添加基础要求。")
                else:
                     # 如果用户提示词已包含，则直接使用用户的提示词
                     final_prompt_template = custom_prompt
                     logger.debug("自定义提示词已包含输出指令。")
            # 如果选择了“通用”但未提供任何提示词
            else:
                logger.warning("未提供有效自定义提示词，将回退使用'标准'风格提示。")
                # 回退到“标准”风格
                style_code = self.style_map.get("标准", "standard")
                final_prompt_template = self._get_preset_prompt_template(target_lang_code, style_code)
        # --- 处理预设风格 ---
        else:
            style_code = style_code_or_prompt # 预设风格代码
            # 获取风格的显示名称
            style_name = next((name for name, code in self.style_map.items() if code == style_code), style_code)
            logger.debug(f"检测到使用预设风格: {style_name} ({style_code})")
            # 调用内部方法获取预设风格的完整指令模板
            final_prompt_template = self._get_preset_prompt_template(target_lang_code, style_code)

        # --- 组合最终 Prompt ---
        # 将上下文、指令模板和待翻译文本组合起来
        full_prompt = f"{context}{final_prompt_template}\n需要翻译的文本：\n{processed_text}"
        logger.debug("最终 Prompt 模板和待翻译文本已组合。")
        # 返回完整的 Prompt
        return full_prompt

    def _get_preset_prompt_template(self, target_lang_code, style_code):
        """
        获取指定目标语言和预设风格的完整提示词指令模板。

        参数:
            target_lang_code (str): 目标语言代码。
            style_code (str): 预设的翻译风格代码。

        返回:
            str: 组合好的指令模板字符串。
        """
        # 获取目标语言名称
        lang_name = next((name for name, code in self.language_map.items() if code == target_lang_code), target_lang_code)
        # 从配置中获取基础指令，提供默认值
        base_prompt = PROMPT_CONFIG['BASE_PROMPT'].get(target_lang_code, f"请将以下文本翻译为{lang_name}：\n")
        # 从配置中获取风格特定指令，默认为空字符串
        style_prompt = PROMPT_CONFIG['STYLE_PROMPT'].get(style_code, "")
        # 从配置中获取语言特定指令，默认为空字符串
        lang_specific = PROMPT_CONFIG['LANG_SPECIFIC_PROMPT'].get(target_lang_code, "")
        # 组合各部分，并添加最终的输出指令
        preset_prompt = f"{base_prompt}{style_prompt}{lang_specific}\n请仅输出翻译后的文本。"
        # 获取风格名称用于日志
        style_name = next((name for name, code in self.style_map.items() if code == style_code), style_code)
        logger.debug(f"已生成 '{style_name}' 风格的预设 Prompt 模板。")
        # 返回生成的模板
        return preset_prompt

    def _process_api_response(self, response, latency, model_name, log_prefix):
        """
        处理从 API 返回的原始响应对象。

        - 验证响应结构和内容。
        - 提取翻译结果文本。
        - 记录 API 调用性能指标（耗时、Token 使用量）。
        - 调用 `_clean_result` 清理提取的文本。

        参数:
            response (openai.types.chat.ChatCompletion): API 返回的响应对象。
            latency (float): API 调用的耗时（秒）。
            model_name (str): 本次调用使用的模型名称（用户界面选择的）。
            log_prefix (str): 用于日志记录的前缀（通常包含文件哈希）。

        返回:
            str: 清理后的翻译结果文本。

        异常:
            ValueError: 如果 API 响应无效或无法提取翻译内容。
        """
        logger.info(f"{log_prefix} 开始处理 API 响应...")
        # --- 验证响应结构 ---
        # 检查响应对象、choices 列表、第一个 choice 的 message 和 message 的 content 是否有效
        if not response or not response.choices or not response.choices[0].message or response.choices[0].message.content is None:
            error_msg = "API响应无效或内容为空。"
            # 记录错误日志，包含部分响应内容（如果可能）
            logger.error(f"{log_prefix} {error_msg} Response: {response}")
            # 抛出 ValueError
            raise ValueError(error_msg)

        # --- 提取结果和记录性能指标 ---
        # 获取翻译结果文本
        result = response.choices[0].message.content
        logger.debug(f"{log_prefix} 原始 API 返回内容 (前100字符): '{result[:100].replace(chr(10), '')}...'")

        # 尝试从 response.usage 中获取 Token 使用量信息，提供默认值 '未知'
        prompt_tokens = getattr(response.usage, 'prompt_tokens', '未知')
        completion_tokens = getattr(response.usage, 'completion_tokens', '未知')
        total_tokens = getattr(response.usage, 'total_tokens', '未知')

        # 记录性能日志
        logger.info(
            f"{log_prefix} API 调用性能指标 | 耗时: {latency:.3f}s | 模型: {model_name} | "
            f"输入Token: {prompt_tokens} | 输出Token: {completion_tokens} | 总Token: {total_tokens}"
        )

        # --- 清理结果 ---
        logger.info(f"{log_prefix} 清理 API 返回结果...")
        # 调用内部方法清理文本
        cleaned_result = self._clean_result(result) # 函数内部有日志
        logger.debug(f"{log_prefix} 清理后结果 (前100字符): '{cleaned_result[:100].replace(chr(10), '')}...'")

        # 检查清理后的结果是否为空
        if not cleaned_result.strip():
            logger.warning(f"{log_prefix} API 返回内容清理后为空字符串。")
            # 返回空字符串，上层会处理这种情况
            return ""
        logger.info(f"{log_prefix} API 响应处理完成。")
        # 返回清理后的结果
        return cleaned_result

    def safe_translate(self, text, target_lang_code, style_code_or_prompt, temp, model_name, file_hash, previous_chunk="", retry=0,
                       log_callback=None, worker=None):
        """
        提供带重试、暂停检查和可选模型降级的安全翻译接口。
        这是外部模块（如 main.py 中的处理逻辑）应该调用的主要翻译方法。

        参数:
            text (str): 需要翻译的文本块。
            target_lang_code (str): 目标语言代码。
            style_code_or_prompt (str): 风格代码或自定义提示词。
            temp (float): 温度参数。
            model_name (str): 初始使用的模型名称。
            file_hash (str): 文件哈希。
            previous_chunk (str, optional): 上下文内容。默认为空。
            retry (int, optional): 当前重试次数（从 0 开始）。默认为 0。
            log_callback (callable, optional): GUI 日志回调函数。默认为 None。
            worker (TranslationWorker, optional): 工作线程实例，用于检查暂停状态。默认为 None。

        返回:
            tuple[str, str]: 一个包含两个元素的元组：
                - str: 翻译结果字符串。如果所有重试都失败，则返回空字符串 ""。
                - str: 最终实际成功完成翻译所使用的模型名称。

        异常:
            PermissionError: 如果发生不可重试的权限/配额/速率错误。
            ValueError: 如果发生不可重试的请求/配置错误。
            Exception: 如果发生其他不可重试的未知错误。
            (注意：TimeoutError 和 ConnectionError 会被内部捕获并用于重试逻辑，
             只有在重试次数耗尽后，它们对应的失败结果（空字符串）会被返回，而不会直接抛出。)
        """
        # 从配置获取最大重试次数
        max_retries = API_CONFIG.get("MAX_RETRY", 3)
        # 日志前缀
        log_prefix = f"[FileHash: {file_hash[:8]}...]" if file_hash else "[No FileHash]"
        logger.debug(f"{log_prefix} 进入 safe_translate | 尝试次数: {retry + 1}/{max_retries + 1} | 模型: {model_name}")
        try:
            # --- 检查暂停状态 ---
            # 如果传入了 worker 实例
            if worker:
                logger.debug(f"{log_prefix} 检查暂停状态...")
                # 调用 worker 的方法等待暂停（如果处于暂停状态）
                worker.wait_if_paused() # wait_if_paused 内部有日志
                logger.debug(f"{log_prefix} 暂停检查通过。")

            # --- 调用核心翻译方法 ---
            # 将所有参数传递给 translate_with_context
            result = self.translate_with_context(
                text, target_lang_code, style_code_or_prompt, temp, model_name,
                file_hash, previous_chunk, log_callback=log_callback
            )
            # 如果 translate_with_context 成功执行没有抛出异常
            logger.info(f"{log_prefix} safe_translate 调用成功 (尝试次数 {retry + 1})。")
            # 返回翻译结果和使用的模型名称
            return result, model_name

        # --- 处理可重试的异常 (TimeoutError, ConnectionError) ---
        except (TimeoutError, ConnectionError) as e:
            error_msg = str(e) # 获取错误信息
            logger.warning(f"{log_prefix} 翻译尝试失败 (可重试错误，第 {retry+1} 次): {error_msg}")
            # 检查是否还有重试次数
            if retry < max_retries:
                # 计算指数退避的等待时间
                wait_time = API_CONFIG.get("RETRY_WAIT_BASE", 0.5) * (2 ** retry)
                # --- 发送 GUI 重试日志 ---
                error_type = "网络超时" if isinstance(e, TimeoutError) else "连接/服务器错误"
                retry_msg = f"{error_type}，将在 {wait_time:.1f} 秒后进行第 {retry + 2}/{max_retries + 1} 次重试..."
                logger.warning(f"{log_prefix} 准备重试... {retry_msg}")
                # 如果有回调函数，发送重试信息到 GUI
                if log_callback: log_callback(f"🔄 {retry_msg}", "retry")
                # --- 结束 GUI 重试日志 ---

                # --- 处理模型降级 ---
                # 调用模型降级逻辑，获取可能的新模型名称
                new_model = self._handle_model_downgrade(model_name, retry)
                # 如果模型发生变化，记录日志并通知 GUI
                if new_model != model_name:
                    model_switch_msg = f"检测到重试，自动从 {model_name} 切换至 {new_model} 模型进行重试"
                    logger.info(f"{log_prefix} {model_switch_msg}")
                    if log_callback: log_callback(f"⚠️ {model_switch_msg}", "warning")
                # 如果模型未变，保持原样
                else:
                    new_model = model_name

                # 等待指定时间
                time.sleep(wait_time)
                # --- 发起递归调用进行重试 ---
                logger.debug(f"{log_prefix} 发起递归调用 safe_translate (重试 {retry + 2})...")
                # 增加重试次数 (retry + 1)，使用可能的新模型 (new_model)
                return self.safe_translate(
                    text, target_lang_code, style_code_or_prompt, temp, new_model,
                    file_hash, previous_chunk, retry + 1, log_callback=log_callback,
                    worker=worker
                )
            # --- 如果重试次数已用尽 ---
            else:
                fail_msg = f"网络或服务器错误 ({error_msg}) 超过最大重试次数 ({max_retries}次)，放弃当前块。"
                logger.error(f"{log_prefix} {fail_msg}", exc_info=False) # 无需堆栈
                # --- 发送 GUI 最终失败日志 ---
                if log_callback: log_callback(f"❌ 翻译失败: {error_msg} (已达最大重试次数)", "error")
                # --- 结束 GUI 最终失败日志 ---
                logger.info(f"{log_prefix} 重试耗尽，safe_translate 返回失败。")
                # 返回空字符串表示该块翻译失败，model_name 保持为最后尝试的模型
                return "", model_name

        # --- 处理不可重试的异常 (PermissionError, ValueError) ---
        except PermissionError as e: # 401, 429, 402
             error_msg = str(e)
             # 生成更友好的 GUI 错误消息
             gui_friendly_error = error_msg
             if "authentication" in error_msg.lower() or "401" in error_msg:
                 gui_friendly_error = "API 认证失败，请检查密钥。"
             elif "rate limit" in error_msg.lower() or "429" in error_msg:
                 gui_friendly_error = "API 请求过于频繁，请稍后再试。"
             elif "insufficient quota" in error_msg.lower() or "402" in error_msg:
                 gui_friendly_error = "API 账户余额不足。"
             logger.error(f"{log_prefix} 翻译尝试失败 (不可重试 - 权限/配额/速率): {error_msg}", exc_info=False)
             # --- 发送 GUI 错误日志 ---
             if log_callback: log_callback(f"❌ 翻译请求失败 (不可重试): {gui_friendly_error}", "error")
             # --- 结束 GUI 错误日志 ---
             # 重新抛出异常，通知上层这是严重错误
             raise e

        except ValueError as e: # 400, 422, 或其他配置/请求问题
             error_msg = str(e)
             gui_friendly_error = error_msg
             # 尝试提供更具体的提示
             if "Invalid" in error_msg or "400" in error_msg or "422" in error_msg:
                 gui_friendly_error = f"API 请求无效: {error_msg}"
             logger.error(f"{log_prefix} 翻译尝试失败 (不可重试 - 请求无效/配置错误): {error_msg}", exc_info=False)
             # --- 发送 GUI 错误日志 ---
             if log_callback: log_callback(f"❌ 翻译请求失败 (不可重试): {gui_friendly_error}", "error")
             # --- 结束 GUI 错误日志 ---
             # 重新抛出异常
             raise e

        # --- 处理其他所有未预料的异常 ---
        except Exception as e:
            error_msg = f"翻译时发生未知错误: {e}"
            logger.error(f"{log_prefix} {error_msg} (尝试次数 {retry + 1})", exc_info=True) # 记录堆栈
            # --- 发送 GUI 错误日志 ---
            fail_msg = f"翻译时发生未知错误: {e}"
            if log_callback: log_callback(f"❌ {fail_msg}", "error")
            # --- 结束 GUI 错误日志 ---
            # 重新抛出异常
            raise e
    # --- 结束 safe_translate ---

    def _handle_model_downgrade(self, current_model, retry_count):
        """
        根据当前模型和重试次数，决定是否进行模型降级。
        目前策略是：仅在第一次重试 (retry_count == 0) 且当前使用的是较昂贵的模型时，
        尝试切换到较便宜的模型。

        参数:
            current_model (str): 当前正在使用的模型名称（用户界面名称）。
            retry_count (int): 当前的重试次数（从 0 开始）。

        返回:
            str: 决定使用的模型名称（可能是原模型，也可能是降级后的模型）。
        """
        # 检查 model_map 是否已初始化
        if not hasattr(self, 'model_map') or not self.model_map:
            logger.error("模型映射表 (model_map) 未初始化，无法执行模型降级。")
            return current_model

        # 从 model_map 中查找特定模型的用户界面名称
        # 使用 next(...) or None 避免在模型名称不存在时出错
        r1_model_name = next((name for name, id in self.model_map.items() if id == 'deepseek-reasoner'), None)
        v3_model_name = next((name for name, id in self.model_map.items() if id == 'deepseek-chat'), None)

        # --- 降级逻辑 ---
        # 检查是否满足所有降级条件：
        # 1. R1 和 V3 模型名称都已在配置中定义
        # 2. 当前是第一次重试 (retry_count == 0)
        # 3. 当前使用的模型是 R1 (假定 R1 比 V3 更贵或更可能失败)
        if r1_model_name and v3_model_name and retry_count == 0 and current_model == r1_model_name:
            logger.info(f"检测到首次重试且当前模型为 {r1_model_name}，尝试降级到 {v3_model_name}。")
            # 返回降级后的模型名称
            return v3_model_name
        # 如果不满足降级条件，返回原模型名称
        logger.debug(f"不执行模型降级 (当前模型: {current_model}, 重试次数: {retry_count})。")
        return current_model
    # --- 结束模型降级处理 ---

    # --- 格式保留与恢复 ---
    def preserve_formatting(self, text, target_lang_code):
        """
        预处理文本，将特定格式（Markdown链接、代码块、行内代码）替换为唯一的占位符。

        参数:
            text (str): 原始输入文本。
            target_lang_code (str): 目标语言代码（当前未使用，但保留以备将来扩展）。

        返回:
            tuple[str, dict]: 一个包含两个元素的元组：
                - str: 处理后的文本，其中格式元素已被占位符替换。
                - dict: 一个字典，键是生成的占位符，值是对应的原始格式内容。
                        结构: {placeholder: original_content}
        """
        logger.debug("开始执行格式保留预处理...")
        replacements = {} # 存储占位符和原始内容的映射
        processed_text = text # 操作副本

        # 定义需要保留的格式的正则表达式模式
        patterns = {
            'LINK': r'\[(.*?)]\((.*?)\)',           # 匹配 Markdown 链接: [text](url)
            'CODEBLOCK': r'```(\w*\n)?([\s\S]*?)```', # 匹配代码块: ```lang\n code ``` 或 ```\n code ```
                                                    # (\w*\n)? 匹配可选的语言标识符和换行符
                                                    # ([\s\S]*?) 非贪婪匹配代码块内容（包括换行符）
            'CODE': r'`([^`\n]+)`',                 # 匹配行内代码: `code` （不允许代码内容包含换行符）
        }

        # 遍历定义的模式
        for prefix, pattern in patterns.items():
            # 为 CODEBLOCK 使用 re.DOTALL 标志，使 `.` 能匹配换行符
            flags = re.DOTALL if prefix == 'CODEBLOCK' else 0
            # 使用 re.finditer 获取所有匹配项的迭代器
            # finditer 返回匹配对象，可以访问匹配内容 (group) 和位置 (span)
            matches_iter = re.finditer(pattern, processed_text, flags=flags)

            # 将迭代器转换为列表，以便反向遍历（从后往前替换避免索引错乱）
            matches_to_process = list(matches_iter)
            # 如果没有找到匹配项，跳过当前模式
            if not matches_to_process:
                continue

            logger.debug(f"找到 {len(matches_to_process)} 个匹配项，准备为 '{prefix}' 类型创建占位符。")

            # 将文本转换为列表，以便在指定位置进行替换
            new_text_list = list(processed_text)

            # 反向遍历匹配项
            for match in reversed(matches_to_process):
                # 获取匹配的起始和结束索引
                start, end = match.span()
                # 获取完整的匹配内容 (例如 `code` 或 [text](url))
                original_content = match.group(0)
                # 创建一个唯一的占位符，并将其与原始内容存入 replacements 字典
                placeholder = self._create_placeholder(original_content, prefix, replacements)
                # 将文本列表中对应位置的内容替换为占位符
                # 注意：这里假设占位符比原始内容短或等长，否则需要调整索引
                # （UUID生成的占位符通常比代码块等长）
                new_text_list[start:end] = list(placeholder)

            # 将修改后的列表合并回字符串
            processed_text = "".join(new_text_list)

        # 记录总结日志
        if replacements:
            logger.info(f"格式保留预处理完成，共创建 {len(replacements)} 个占位符。")
        else:
            logger.debug("格式保留预处理完成，未找到需要替换的格式。")
        # 返回处理后的文本和替换项字典
        return processed_text, replacements

    def _create_placeholder(self, original_content, prefix, replacements):
        """
        为给定的原始内容生成一个唯一的占位符，并将其存储在 `replacements` 字典中。

        参数:
            original_content (str): 需要被替换的原始格式内容。
            prefix (str): 用于标识格式类型的字符串 (例如 'LINK', 'CODEBLOCK')。
            replacements (dict): 用于存储占位符到原始内容映射的字典。

        返回:
            str: 生成的唯一占位符字符串。
        """
        # 构建占位符字符串，包含前缀和 UUID 的一部分以确保唯一性
        placeholder = f"__TRANSLATION_PLACEHOLDER_{prefix}_{uuid.uuid4().hex[:6]}__"
        # 将占位符和原始内容添加到映射字典中
        replacements[placeholder] = original_content
        # 记录创建的占位符和部分原始内容（用于调试）
        log_content = original_content[:50].replace('\n', '\\n') + ('...' if len(original_content) > 50 else '')
        logger.debug(f"创建占位符: {placeholder} -> '{log_content}'")
        # 返回占位符
        return placeholder

    def restore_formatting(self, translated_text, replacements, target_lang_code):
        """
        将翻译后文本中的占位符替换回它们对应的原始格式内容。

        参数:
            translated_text (str): 包含占位符的翻译后文本。
            replacements (dict): 包含占位符到原始内容映射的字典。
            target_lang_code (str): 目标语言代码（当前未使用）。

        返回:
            str: 格式已恢复的最终文本。
        """
        # 如果替换字典为空，无需操作，直接返回原文
        if not replacements:
            logger.debug("无需还原格式，替换列表为空。")
            return translated_text

        logger.info(f"开始还原格式，共 {len(replacements)} 个占位符需要处理...")
        restored_count = 0  # 记录成功还原的占位符实例总数
        missing_count = 0   # 记录未在翻译结果中找到的占位符类型数量

        # --- 按占位符长度降序排序 ---
        # 优先替换较长的占位符可以避免短占位符是长占位符一部分时导致的错误替换
        # 例如，防止 `__CODE_1__` 被 `__CODE_12__` 的一部分错误匹配
        sorted_placeholders = sorted(replacements.keys(), key=len, reverse=True)

        temp_translated_text = translated_text # 操作副本
        # 遍历排序后的占位符
        for ph in sorted_placeholders:
            # 获取该占位符对应的原始内容
            original = replacements[ph]
            # 检查占位符在翻译文本中出现的次数
            occurrences = temp_translated_text.count(ph)
            # 如果占位符存在
            if occurrences > 0:
                # 将所有出现的占位符替换回原始内容
                temp_translated_text = temp_translated_text.replace(ph, original)
                # 累加还原的实例数
                restored_count += occurrences
                # 记录还原日志（部分内容）
                log_content = original[:50].replace('\n', '\\n') + ('...' if len(original) > 50 else '')
                logger.debug(f"  - 已还原 {occurrences} 次: {ph} -> '{log_content}'")
            # 如果占位符在翻译结果中未找到
            else:
                 missing_count += 1 # 增加未找到计数
                 logger.warning(f"  - 占位符未在翻译结果中找到: {ph}")

        # --- 记录总结日志 ---
        if missing_count > 0:
             logger.warning(f"格式还原警告: {missing_count} 个占位符未在翻译结果中找到。可能影响最终输出。")
        else:
             logger.info(f"格式还原成功完成，所有 {len(replacements)} 类占位符均已处理 (共还原 {restored_count} 个实例)。")
        # 记录部分还原后的文本（用于调试）
        logger.debug(f"格式还原后的文本 (前100字符): '{temp_translated_text[:100].replace(chr(10), '')}...'")
        # 返回格式还原后的文本
        return temp_translated_text
    # --- 结束格式保留与恢复 ---

    # --- API 结果清理函数 ---
    def _clean_result(self, result):
        """
        清理从 API 返回的原始翻译文本，去除可能存在的无关前缀、多余空白等。

        参数:
            result (str): 从 API 获取的原始响应文本。

        返回:
            str: 清理后的文本。
        """
        logger.debug("开始清理 API 返回结果...")
        original_length = len(result) # 记录原始长度
        cleaned = result # 操作副本

        # 1. 移除可能由模型添加的外部引号以及首尾的空格和换行符
        cleaned = cleaned.strip('"\'\n ')
        if len(cleaned) != original_length: logger.debug("已移除首尾引号、换行或空格。")

        # 2. 移除常见的回应前缀（例如 "翻译结果："）
        # 定义一个正则表达式，匹配多种语言中可能的前缀，忽略大小写
        prefix_pattern = r'^(?:翻译结果|translation result|翻訳結果|번역 결과)\s*[:：]\s*'
        # 使用 re.sub 进行替换
        cleaned_before_prefix = cleaned
        cleaned = re.sub(prefix_pattern, '', cleaned, flags=re.IGNORECASE | re.UNICODE)
        if cleaned != cleaned_before_prefix: logger.debug("已移除常见的模型回复前缀。")

        # 3. 合并连续的多个换行符为最多两个换行符（保留段落间的空行）
        # 统计三个或更多连续换行符的情况，用于判断是否进行了合并
        original_newlines = cleaned.count('\n\n\n')
        # 使用正则表达式将三个或更多连续换行符替换为两个
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        if original_newlines > 0: logger.debug("已合并多个连续换行符为双换行。")

        # 4. 再次去除可能因移除前缀而产生的新的首尾空白
        final_cleaned = cleaned.strip()
        final_length = len(final_cleaned) # 获取最终长度

        # 记录清理效果
        if final_length < original_length: logger.debug(f"清理完成，长度从 {original_length} 减少到 {final_length}。")
        else: logger.debug("清理完成，未发现需要移除或修改的内容。")
        # 返回最终清理后的文本
        return final_cleaned
    # --- 结束 API 结果清理函数 ---