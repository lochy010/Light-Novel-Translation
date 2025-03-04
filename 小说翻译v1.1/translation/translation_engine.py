# transactions\translation_engine.py
"""
翻译引擎核心模块
功能：实现翻译业务逻辑，集成AI翻译API，管理翻译上下文
核心机制：
- 集成DeepSeek翻译API，支持多语言、多风格翻译
- 实现带上下文的翻译流程
- 提供错误重试机制和模型降级策略
- 支持格式保留和缓存优化
"""

import logging
import time
import re
import uuid

from openai import OpenAI
from cache.cache_manager import TranslationCache
from file_processor.file_handler import dynamic_split
from config.settings import TRANSLATION_CONFIG, PROMPT_CONFIG  # 新增配置导入

# 初始化缓存管理器实例
cache = TranslationCache()
logger = logging.getLogger("TranslationEngine")


class TranslationEngine:
    """翻译引擎核心类

    属性：
    - client: DeepSeek API客户端
    - language_map: 语言名称到代码的映射
    - style_map: 翻译风格名称到代码的映射
    - model_map: 模型名称到API模型标识的映射

    功能：
    - 初始化翻译引擎配置
    - 实现带上下文的翻译逻辑
    - 处理API响应和错误重试
    - 保留和恢复文本格式
    """

    def __init__(self, api_key):
        """初始化翻译引擎
        :param api_key: DeepSeek API密钥
        """
        logger.info("[TranslationEngine] 初始化翻译引擎")
        # 初始化API客户端
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            timeout=180,
        )
        # 从配置中加载语言、风格和模型映射
        self.language_map = TRANSLATION_CONFIG["LANGUAGE_MAP"]
        self.style_map = TRANSLATION_CONFIG["STYLE_MAP"]
        self.model_map = TRANSLATION_CONFIG["MODEL_MAP"]
        logger.debug("[TranslationEngine] 翻译引擎配置完成 | 支持语言: %s | 支持风格: %s",
                     self.language_map.keys(), self.style_map.keys())

    def translate_with_context(self, text, target_lang, style, temperature, model_name, file_hash, previous_chunk="",
                               log_callback=None):
        """
        带上下文的翻译核心方法
        :param text: 待翻译文本
        :param target_lang: 目标语言代码
        :param style: 翻译风格代码
        :param temperature: 温度值，控制生成文本的随机性
        :param model_name: 使用的模型名称
        :param file_hash: 文件哈希，用于缓存键生成
        :param previous_chunk: 前文内容，用于上下文关联
        :param log_callback: 日志回调函数，用于在GUI中输出缓存命中信息
        :return: 翻译结果
        """
        logger.debug("[TranslationEngine] 开始翻译处理 | 目标语言: %s | 风格: %s | 模型: %s | 文件哈希: %s",
                     target_lang, style, model_name, file_hash[:8])

        # 格式保留预处理
        processed_text, replacements = self.preserve_formatting(text, target_lang)
        # 生成缓存键
        cache_key = cache.get_key(text, target_lang, style, file_hash)

        # 缓存检查，同时传入日志回调函数，将信息输出到GUI实时日志中
        if cached := cache.get(
                text, target_lang, style, file_hash,
                log_callback=lambda msg: (self.worker.log.emit(msg, "cache") if hasattr(self, 'worker')
                else (log_callback(msg) if log_callback else None))
        ):
            logger.info("[TranslationEngine] 缓存命中...")
            return self.restore_formatting(cached, replacements, target_lang)

        # 构建上下文
        context = self._build_context(previous_chunk, target_lang)
        logger.debug("[TranslationEngine] 上下文摘要 | 长度: %d 字符", len(context))

        try:
            # API调用
            start_time = time.time()
            response = self.client.chat.completions.create(
                model=self.model_map[model_name],
                messages=[{"role": "user", "content": self._build_prompt(target_lang, style, context, processed_text)}],
                temperature=float(temperature),
                max_tokens=8192,
                timeout=180
                )
            result = self._process_api_response(response, start_time, model_name)

            # 缓存结果
            cache.set(text, target_lang, style, result, file_hash)
            logger.debug("[TranslationEngine] 翻译结果处理完成 | 原始长度: %d | 翻译后长度: %d",
                         len(text), len(result))
            return self.restore_formatting(result, replacements, target_lang)

        except Exception as e:
            logger.error("[TranslationEngine] API调用失败: %s", str(e), exc_info=True)
            raise Exception(f"API调用失败: {str(e)}")

    def _build_context(self, previous_chunk, target_lang):
        """构建上下文摘要（优化上下文截取逻辑）
        :param previous_chunk: 前文内容
        :param target_lang: 目标语言代码
        :return: 上下文摘要字符串
        """
        if not previous_chunk:
            return ""
        # 根据目标语言设置最大上下文长度
        max_context_length = TRANSLATION_CONFIG["CONTEXT_LENGTH"].get(target_lang, 200)
        return f"前文摘要：{previous_chunk[-max_context_length:]}\n\n"

    def _build_prompt(self, target_lang, style, context, processed_text):
        """构造带详细日志的prompt
        :param target_lang: 目标语言代码
        :param style: 翻译风格代码
        :param context: 上下文摘要
        :param processed_text: 预处理后的文本
        :return: 完整的prompt字符串
        """
        prompt_template = self._get_prompt_template(target_lang, style)
        logger.debug("[TranslationEngine] Prompt构造完成 | 总长度: %d 字符", len(prompt_template))
        return f"{context}{prompt_template}\n需要翻译的文本：\n{processed_text}"

    def _get_prompt_template(self, target_lang, style):
        """获取翻译提示模板
        从配置文件中加载基础提示词和风格提示词
        :param target_lang: 目标语言代码
        :param style: 翻译风格代码
        :return: 翻译提示模板字符串
        """
        base_prompt = PROMPT_CONFIG["BASE_PROMPT"].get(target_lang, "")
        style_prompt = PROMPT_CONFIG["STYLE_PROMPT"].get(style, "")
        return f"{base_prompt}{style_prompt}"

    def _get_lang_specific_instructions(self, target_lang):
        """生成语言专项要求
        从配置文件中加载语言特定要求
        :param target_lang: 目标语言代码
        :return: 语言专项要求字符串
        """
        return PROMPT_CONFIG["LANG_SPECIFIC_PROMPT"].get(target_lang, "")

    def _process_api_response(self, response, start_time, model_name):
        """处理API响应并记录性能指标
        :param response: API响应对象
        :param start_time: API调用开始时间
        :param model_name: 使用的模型名称
        :return: 处理后的翻译结果
        """
        if not response.choices[0].message.content:
            raise ValueError("API返回空内容")
        result = response.choices[0].message.content
        result = self._clean_result(result)
        latency = time.time() - start_time
        logger.info(
            "[TranslationEngine] API调用成功 | 耗时: %.2fs | 模型: %s | 使用Token: %d",
            latency, model_name, response.usage.total_tokens
        )
        return result

    def safe_translate(self, text, target_lang, style, temp, model_name, file_hash, previous_chunk="", retry=0,
                       log_callback=None):
        """
        增强安全性的翻译方法（支持暂停检查）
        :param text: 待翻译文本
        :param target_lang: 用户选择的目标语言（例如 'zh'、'en' 等）
        :param style: 用户选择的风格（例如 "standard"、"light_novel"、"formal"）
        :param temp: 温度值
        :param model_name: 使用的模型名称
        :param file_hash: 文件哈希，用于缓存键生成
        :param previous_chunk: 上下文文本（默认为空字符串）
        :param retry: 当前重试次数（默认为0）
        :param log_callback: 日志回调函数，用于在GUI中输出重试等日志信息
        :return: 翻译结果以及实际使用的模型名称
        """
        logger.debug("[TranslationEngine] 安全翻译调用 | 重试次数: %d | 模型: %s", retry, model_name)
        try:
            if hasattr(self, 'worker'):
                self.worker.wait_if_paused()
                logger.debug("[TranslationEngine] 通过暂停状态检查")

            # 调用translate_with_context，并传递log_callback
            result = self.translate_with_context(
                text,
                self.language_map[target_lang],
                style,
                temp,
                model_name,
                file_hash,
                previous_chunk,
                log_callback=log_callback
            )
            return result, model_name

        except Exception as e:
            if retry < 3:
                wait_time = 2 ** retry + 0.5
                logger.warning("[TranslationEngine] 翻译失败，准备重试...")
                if log_callback:
                    log_callback(f"请求超时，第{retry + 1}次重试（等待{wait_time:.1f}秒）")
                new_model = self._handle_model_downgrade(model_name, retry)
                time.sleep(wait_time)
                return self.safe_translate(
                    text, target_lang, style, temp, new_model,
                    file_hash, previous_chunk, retry + 1, log_callback=log_callback
                )
            else:
                logger.error("[TranslationEngine] 连续重试失败，启用分块降级 | 原始长度: %d", len(text))
                return self._handle_fallback(text, target_lang, style, temp, model_name, file_hash)

    def _handle_model_downgrade(self, current_model, retry_count):
        """处理模型降级逻辑
        :param current_model: 当前使用的模型名称
        :param retry_count: 当前重试次数
        :return: 降级后的模型名称
        """
        if retry_count >= 1 and current_model == "DeepSeek-R1":
            logger.warning("[TranslationEngine] 模型自动降级...")
            if hasattr(self, 'worker'):
                self.worker.log.emit(
                    "检测到响应延迟，自动切换至V3模型保障稳定性",
                    "warning"
                )
            return "DeepSeek-V3"
        return current_model

    def _handle_fallback(self, text, target_lang, style, temp, model_name, file_hash):
        """分块降级处理
        :param text: 待翻译文本
        :param target_lang: 目标语言代码
        :param style: 翻译风格代码
        :param temp: 温度值
        :param model_name: 使用的模型名称
        :param file_hash: 文件哈希，用于缓存键生成
        :return: 分块翻译后的结果
        """
        sub_chunks = dynamic_split(text, self.language_map[target_lang], 3000)
        translated_parts = []
        current_model = model_name
        for idx, sub in enumerate(sub_chunks):
            if hasattr(self, 'worker'):
                self.worker.wait_if_paused()
            previous_context = "\n".join(translated_parts[-3:])
            # 此处不需要传递日志回调，可传入空回调函数
            translated, current_model = self.safe_translate(
                sub, target_lang, style, temp, current_model,
                file_hash, previous_context, log_callback=lambda msg: None
            )
            translated_parts.append(translated)
        return '\n'.join(translated_parts), current_model

    # ---------- 格式保留方法 ---------- #
    def preserve_formatting(self, text, target_lang):
        """增强格式保留方法
        :param text: 原始文本
        :param target_lang: 目标语言代码
        :return: 处理后的文本和占位符映射表
        """
        replacements = {}
        # 保留超链接
        text = re.sub(r'\[(.*?)\]\((.*?)\)',
                      lambda m: self._create_placeholder(m, 'LINK', replacements), text)
        # 保留代码块
        text = re.sub(r'```(.*?)```',
                      lambda m: self._create_placeholder(m, 'CODE', replacements), text, flags=re.DOTALL)
        # 语言特定预处理
        if target_lang == 'ja':
            text = re.sub(r'(\d+)円', r'￥\1', text)
        elif target_lang == 'ko':
            text = re.sub(r'(\d+)원', r'₩\1', text)
        logger.debug("[TranslationEngine] 格式预处理完成 | 替换项: %d", len(replacements))
        return text, replacements

    def _create_placeholder(self, match, prefix, replacements):
        """生成唯一占位符
        :param match: 正则匹配对象
        :param prefix: 占位符前缀
        :param replacements: 占位符映射表
        :return: 生成的占位符
        """
        placeholder = f"[{prefix}_{uuid.uuid4().hex[:8]}]"
        replacements[placeholder] = match.group(0)
        return placeholder

    def restore_formatting(self, translated_text, replacements, target_lang):
        """还原格式（增强后处理）
        :param translated_text: 翻译后的文本
        :param replacements: 占位符映射表
        :param target_lang: 目标语言代码
        :return: 还原格式后的文本
        """
        for ph, original in replacements.items():
            translated_text = translated_text.replace(ph, original)
        if target_lang == 'ja':
            translated_text = re.sub(r'￥(\d+)', r'\1円', translated_text)
        elif target_lang == 'ko':
            translated_text = re.sub(r'₩(\d+)', r'\1원', translated_text)
        logger.debug("[TranslationEngine] 格式还原完成 | 替换项: %d", len(replacements))
        return translated_text

    def _clean_result(self, result):
        """清理API返回结果
        :param result: API返回的原始结果
        :return: 清理后的结果
        """
        result = result.strip('"\'\n ')
        result = re.sub(r'^翻译结果[：:]\s*', '', result)
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result