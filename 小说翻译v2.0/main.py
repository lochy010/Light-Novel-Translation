# main.py
"""
主程序入口模块 (main.py)

功能：
这是整个应用程序的启动点。它负责初始化所有核心组件（日志、配置、缓存、翻译引擎、GUI），
处理命令行参数（通过 QApplication），协调各模块之间的交互，并启动 Qt 事件循环。
该模块还包含了处理单个文档的核心业务逻辑 (`process_single_document`)，
这个逻辑会被后台工作线程 (TranslationWorker) 调用。

执行流程：
1. 设置全局日志记录系统 (`setup_logging`)。
2. 定义应用程序状态码常量。
3. 定义 `Application` 类作为主控制器。
4. 在 `Application.__init__` 中：
   - 初始化 QApplication。
   - 验证配置文件路径 (`validate_config_paths`)。
   - 验证并读取 API 密钥 (`validate_config`)。
   - 初始化缓存管理器 (`TranslationCache`) 并加载缓存。
   - 初始化翻译引擎 (`TranslationEngine`)。
   - 初始化图形用户界面 (`TranslationGUI`) 并显示。
   - 处理初始化过程中可能出现的配置错误或严重错误。
5. 在 `Application` 类中定义 `process_single_document` 方法，封装处理单个文件的完整流程：
   - 文件校验（存在性、大小、哈希）。
   - 文本提取（根据文件类型）。
   - 参数准备（语言、风格、模型、温度）。
   - 智能分块 (`dynamic_split`)。
   - 逐块翻译（调用 `TranslationEngine.safe_translate`，处理上下文、缓存、重试）。
   - 结果合并与保存（根据用户选择的格式）。
   - 通过 `worker` 对象更新 GUI 状态和进度。
6. 在 `Application` 类中定义 `run` 方法，启动 Qt 事件循环。
7. 在 `if __name__ == "__main__":` 块中：
   - 调用 `setup_logging`。
   - 创建 `Application` 实例。
   - 调用 `app_instance.run()` 启动应用。
   - 处理主流程中未捕获的异常。
   - 确保日志系统关闭并以正确的退出码退出程序。
"""

# 导入 sys 模块，用于访问命令行参数 (sys.argv) 和退出程序 (sys.exit)。
import sys
# 导入 logging 模块，用于配置和使用日志记录。
import logging
# 导入 os 模块，用于文件和目录操作（如创建目录、获取文件名、检查路径等）。
import os
# 导入 datetime 模块，用于生成带时间戳的文件名（例如日志文件、输出文件）。
from datetime import datetime

# --- PyQt6 导入 ---
# 从 PyQt6.QtGui 导入 QFont 类，用于设置 GUI 的全局字体。
from PyQt6.QtGui import QFont
# 从 PyQt6.QtWidgets 导入 QApplication (应用程序对象) 和 QMessageBox (消息框)。
from PyQt6.QtWidgets import QApplication, QMessageBox
# --- 结束 PyQt6 导入 ---

# --- 自定义模块导入 ---
# 导入 GUI 界面类
from gui.gui_interface import TranslationGUI
# 导入配置管理相关的函数和异常类
from config.config_manager import validate_config, validate_config_paths, ConfigValidationError
# 导入缓存管理器类
from cache.cache_manager import TranslationCache
# 导入翻译引擎类
from translation.translation_engine import TranslationEngine
# 导入文件处理相关的函数
from file_processor.file_handler import (
    get_file_hash, extract_text_from_docx, save_as_word,
    dynamic_split, save_as_txt, extract_text_from_txt
)
# 导入全局配置文件中的常量字典
from config.settings import (
    PATH_CONFIG, GUI_CONFIG, FILE_HANDLER_CONFIG,
    TRANSLATION_CONFIG, API_CONFIG
)
# --- 结束自定义模块导入 ---

# --- 文件列表项状态码定义 ---
# 这些常量字符串用于表示文件在处理过程中的不同状态。
# 在 main.py 和 gui_interface.py 中保持一致，用于状态更新通信。
STATUS_PENDING = "PENDING"              # 待处理
STATUS_PROCESSING = "PROCESSING"        # 正在处理（通用状态）
STATUS_HASHING = "HASHING"              # 正在计算哈希值
STATUS_PARSING = "PARSING"              # 正在解析文件内容
STATUS_SPLITTING = "SPLITTING"          # 正在进行智能分块
STATUS_TRANSLATING = "TRANSLATING"      # 正在调用 API 进行翻译
STATUS_CACHED = "CACHED"                # 翻译结果来自缓存
STATUS_SAVING = "SAVING"                # 正在保存翻译结果
STATUS_COMPLETED_OK = "COMPLETED_OK"    # 处理成功完成
STATUS_COMPLETED_WARN = "COMPLETED_WARN" # 处理完成但有警告
STATUS_SKIPPED_EMPTY = "SKIPPED_EMPTY"  # 因文件为空而跳过
STATUS_SKIPPED_NO_CONTENT = "SKIPPED_NO_CONTENT" # 因内容为空而跳过
STATUS_ERROR_HASH = "ERROR_HASH"          # 计算哈希时出错
STATUS_ERROR_PARSE = "ERROR_PARSE"        # 解析文件时出错
STATUS_ERROR_SPLIT = "ERROR_SPLIT"        # 分块时出错
STATUS_ERROR_SAVE = "ERROR_SAVE"          # 保存文件时出错
STATUS_ERROR_TRANSLATE = "ERROR_TRANSLATE" # 翻译过程中出错
STATUS_ERROR_CRITICAL = "ERROR_CRITICAL"  # 发生严重错误导致处理中止
# --- 结束状态码常量定义 ---

# --- 自定义日志 Formatter ---
class CustomLogFormatter(logging.Formatter):
    """
    自定义日志格式化器。
    继承自 `logging.Formatter`，重写 `format` 方法，
    目的是在日志记录中将完整的文件路径 (`record.pathname`) 替换为不带后缀的模块名 (`record.filename`)。
    例如，将 `.../myapp/gui/gui_interface.py` 显示为 `gui_interface`。
    """
    def format(self, record):
        """
        格式化指定的日志记录。

        参数:
            record (logging.LogRecord): 需要格式化的日志记录对象。

        返回:
            str: 格式化后的日志字符串。
        """
        # 获取原始记录中的完整文件路径
        original_pathname = record.pathname
        # 使用 os.path.basename 获取文件名（带后缀）
        # 使用 os.path.splitext 分离文件名和后缀，取第一部分（不带后缀的文件名）
        module_name = os.path.splitext(os.path.basename(original_pathname))[0]
        # 将 LogRecord 对象中的 filename 属性修改为处理后的模块名
        # Formatter 基类会使用 record.filename 来填充 '%(filename)s' 占位符
        record.filename = module_name
        # 调用父类的 format 方法，使用更新后的 record 和原始的格式化字符串完成格式化
        return super().format(record)
# --- 结束自定义日志 Formatter ---

# --- 日志系统设置函数 ---
def setup_logging():
    """
    配置应用程序的全局日志系统。

    - 创建日志目录（如果不存在）。
    - 定义日志格式，使用自定义的 `CustomLogFormatter`。
    - 创建文件处理器 (FileHandler)，将日志写入带时间戳的日志文件。
    - 创建流处理器 (StreamHandler)，将日志输出到控制台。
    - 将处理器添加到根日志记录器 (root logger)。
    - 设置根日志记录器的级别为 INFO。
    - 设置特定模块（包括第三方库如 openai, httpx）的日志级别，以控制日志详细程度。
    - 处理日志设置过程中可能发生的异常。
    """
    try:
        # 尝试从配置获取日志目录路径，默认为 "logs"
        log_dir = PATH_CONFIG.get("LOG_DIR", "logs")
        # 创建日志目录，exist_ok=True 表示如果目录已存在则不报错
        os.makedirs(log_dir, exist_ok=True)

        # --- 定义日志格式字符串 ---
        # %(asctime)s: 时间戳
        # [%(filename)s]: 自定义 Formatter 处理后的模块名
        # %(levelname)s: 日志级别 (INFO, WARNING, ERROR 等)
        # %(message)s: 日志消息本身
        log_format = "%(asctime)s - [%(filename)s] - %(levelname)s - %(message)s"
        # --- 结束日志格式字符串 ---

        # 生成带时间戳的日志文件名
        log_file = datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
        # 构建完整的日志文件路径
        log_file_path = os.path.join(log_dir, log_file)

        # --- 配置根日志记录器 ---
        # 获取根日志记录器
        root_logger = logging.getLogger()
        # 移除所有已存在的处理器，防止重复添加（特别是在重新加载或调试时）
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # --- 创建处理器 ---
        # 文件处理器，写入到文件，使用 UTF-8 编码
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        # 流处理器，输出到控制台 (stderr)
        stream_handler = logging.StreamHandler()

        # --- 创建并应用自定义 Formatter ---
        formatter = CustomLogFormatter(log_format) # 使用自定义 Formatter
        file_handler.setFormatter(formatter)     # 为文件处理器设置 Formatter
        stream_handler.setFormatter(formatter)   # 为流处理器设置 Formatter

        # --- 将处理器添加到根记录器 ---
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)

        # --- 设置日志级别 ---
        # 设置根记录器的级别为 INFO，低于此级别的日志将被忽略
        root_logger.setLevel(logging.INFO)

        # 记录日志系统初始化成功的消息
        logging.info(f"日志系统初始化成功，日志文件: {log_file_path}")

        # --- 调整特定模块的日志级别 ---
        # 可以根据需要设置不同模块的日志详细程度
        # 例如，将核心逻辑设置为 INFO 或 DEBUG，将不太重要的模块设置为 WARNING
        logging.getLogger("translation_engine").setLevel(logging.INFO)
        logging.getLogger("file_handler").setLevel(logging.INFO)
        logging.getLogger("cache_manager").setLevel(logging.INFO)
        logging.getLogger("config_manager").setLevel(logging.INFO)
        logging.getLogger("gui_interface").setLevel(logging.INFO) # GUI 操作日志也记录 INFO
        logging.getLogger("TranslationWorker").setLevel(logging.INFO) # 工作线程日志
        logging.getLogger("main").setLevel(logging.INFO) # 主程序日志

        # --- 降低第三方库的日志级别，减少干扰 ---
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        # --- 结束第三方库日志级别调整 ---

        logging.info("日志级别配置完成。") # 添加日志级别配置完成的记录

    except Exception as e:
        # 如果日志系统设置失败，这是致命错误
        # 打印错误到标准错误流，因为日志系统可能无法工作
        print(f"FATAL: 日志系统初始化失败: {e}", file=sys.stderr)
        sys.exit(1) # 退出程序
# --- 结束日志系统设置函数 ---


# --- 主应用程序类 ---
class Application:
    """
    主应用程序控制器类。
    负责整合应用程序的所有组件，管理初始化流程和核心业务逻辑的调用。
    """

    def __init__(self):
        """
        初始化 Application 实例。
        执行应用程序启动所需的所有步骤，包括初始化 Qt、验证配置、
        设置核心组件（缓存、引擎）和创建用户界面。
        处理初始化过程中可能发生的各种错误。
        """
        # --- 获取主程序日志记录器 ---
        self.logger = logging.getLogger("main") # 使用 'main' 作为记录器名称
        # --- 记录初始化开始 ---
        self.logger.info("==============================================")
        self.logger.info("       应用程序初始化流程启动        ")
        self.logger.info("==============================================")

        # 初始化实例变量
        self.qt_app = None # QApplication 实例
        self.api_key = None # API 密钥
        self.cache_manager = None # 缓存管理器实例
        self.engine = None # 翻译引擎实例
        self.gui = None # GUI 实例

        try:
            # --- 步骤 1: 初始化 QApplication ---
            self.logger.info("初始化 Qt Application...")
            # 获取当前的 QApplication 实例（如果存在）
            self.qt_app = QApplication.instance()
            # 如果不存在，则创建一个新的实例
            if self.qt_app is None:
                self.qt_app = QApplication(sys.argv) # sys.argv 用于传递命令行参数给 Qt
                self.logger.info("QApplication 实例已成功创建。")
            else:
                self.logger.info("已使用现有 QApplication 实例。")

            # --- 步骤 2: 验证配置路径 ---
            self.logger.info("验证配置文件路径...")
            # 调用 config_manager 中的函数验证路径并尝试创建目录
            validate_config_paths() # 如果失败会抛出 ConfigValidationError
            self.logger.info("所有配置路径验证通过，必要的目录已检查或创建。")

            # --- 步骤 3: 验证 API 密钥 ---
            self.logger.info("验证 API 密钥...")
            # 调用 config_manager 中的函数读取并验证 API 密钥
            self.api_key = validate_config() # 如果失败会抛出 ConfigValidationError
            self.logger.info("API 密钥已成功读取并验证。")

            # --- 步骤 4: 初始化缓存管理器 ---
            self.logger.info("初始化并加载缓存管理器...")
            # 创建 TranslationCache 实例
            self.cache_manager = TranslationCache()
            # 从磁盘加载缓存数据
            self.cache_manager.load_cache() # load_cache 方法内部有详细日志
            self.logger.info("缓存管理器初始化完成。")

            # --- 步骤 5: 初始化核心组件和 UI ---
            self.logger.info("初始化核心翻译引擎和用户界面...")
            # 调用内部方法初始化翻译引擎
            self._init_core_components()
            # 调用内部方法初始化 GUI
            self._init_ui()
            self.logger.info("核心组件和用户界面初始化完成。")

            # --- 记录初始化成功 ---
            self.logger.info("----------------------------------------------")
            self.logger.info("       应用程序初始化成功        ")
            self.logger.info("----------------------------------------------")

        # --- 异常处理 ---
        except ConfigValidationError as e:
            # 处理配置相关的错误 (由 validate_config_paths 或 validate_config 抛出)
            config_error_msg = f"配置错误导致初始化失败: {str(e)}"
            self.logger.critical(config_error_msg) # 记录严重错误
            # 尝试显示错误消息给用户
            self._show_critical_error(f"应用程序启动失败\n\n{config_error_msg}")
            sys.exit(1) # 退出程序

        except SystemExit as e:
             # 捕获由 sys.exit() 引发的退出请求（例如在 setup_logging 中）
             self.logger.warning(f"应用程序因 SystemExit 请求退出 (退出码: {e.code})。")
             raise # 重新抛出，让外部 __main__ 处理退出

        except Exception as e:
            # 捕获初始化过程中所有其他未预料的严重错误
            critical_error_msg = f"应用程序初始化过程中发生未捕获的严重错误: {e}"
            self.logger.critical(critical_error_msg, exc_info=True) # 记录堆栈信息
            # 尝试显示错误消息给用户
            self._show_critical_error(f"应用程序初始化失败，无法启动。\n请查看日志文件以获取详细信息。\n错误: {e}")
            sys.exit(1) # 退出程序

    def _show_critical_error(self, message):
        """
        内部辅助方法，尝试使用 QMessageBox 显示严重错误信息。
        如果 QApplication 尚未初始化，会尝试创建临时的实例。

        参数:
            message (str): 需要显示的错误消息文本。
        """
        # 先记录错误日志，再尝试显示
        self.logger.error(f"尝试向用户显示严重错误: {message}")
        # 检查 QApplication 实例是否存在
        if self.qt_app is None:
            # 如果不存在，尝试创建一个临时的 QApplication 实例
            try:
                self.logger.warning("QApplication 实例不存在，尝试创建临时实例以显示错误。")
                self.qt_app = QApplication(sys.argv)
            except Exception as app_create_err:
                 # 如果连 QApplication 都无法创建，记录关键错误并打印到 stderr
                 error_log = f"CRITICAL ERROR: {message}\nAdditionally, failed to create QApplication: {app_create_err}"
                 self.logger.critical(error_log)
                 print(error_log, file=sys.stderr)
                 return # 无法显示，直接返回

        # 使用 QMessageBox 显示严重错误对话框
        try:
             # 第一个参数 None 表示没有父窗口
             QMessageBox.critical(None, "严重错误", message)
             self.logger.info("严重错误消息已成功显示给用户。")
        except Exception as mb_exc:
            # 如果显示消息框时也发生错误，记录日志并打印到 stderr
            error_log = f"CRITICAL ERROR: {message}\nAdditionally, failed to show message box: {mb_exc}"
            self.logger.error(error_log) # 使用 error 级别记录显示失败
            print(error_log, file=sys.stderr)

    def _init_core_components(self):
        """初始化核心业务逻辑组件，主要是翻译引擎。"""
        self.logger.info("开始初始化核心组件: TranslationEngine...")
        try:
            # 创建 TranslationEngine 实例，传入 API 密钥和缓存管理器
            self.engine = TranslationEngine(self.api_key, self.cache_manager)
            self.logger.info("TranslationEngine 初始化成功。")
        except Exception as e:
            # 处理翻译引擎初始化失败的情况
            engine_error_msg = f"初始化 TranslationEngine 失败: {e}"
            self.logger.critical(engine_error_msg, exc_info=True)
            # 抛出 RuntimeError，由外层 __init__ 的 try-except 块捕获
            raise RuntimeError(engine_error_msg) from e

    def _init_ui(self):
        """初始化图形用户界面 (GUI)。"""
        self.logger.info("开始初始化用户界面 (GUI)...")
        try:
            # --- 设置全局 GUI 样式 ---
            # 设置全局字体
            font = QFont(GUI_CONFIG["FONT"]["family"], GUI_CONFIG["FONT"]["size"])
            self.qt_app.setFont(font)
            # 设置 Qt 控件样式（'Fusion' 是一个跨平台较好的样式）
            self.qt_app.setStyle("Fusion")
            self.logger.debug(f"GUI 全局字体设置为: {GUI_CONFIG['FONT']['family']} {GUI_CONFIG['FONT']['size']}pt")
            self.logger.debug("GUI 样式设置为: Fusion")

            # --- 创建 GUI 实例 ---
            # 创建 TranslationGUI 实例，传入 Application 自身和缓存管理器
            self.gui = TranslationGUI(self, self.cache_manager)
            self.logger.info("TranslationGUI 实例已创建。")

            # --- 将 GUI 实例传递给引擎 ---
            # 如果引擎需要访问 GUI 控件（例如获取自定义提示词），需要建立引用
            if self.engine:
                self.engine.gui = self.gui
                self.logger.debug("GUI 实例已传递给 TranslationEngine。")
            else:
                # 如果引擎初始化失败，记录警告
                self.logger.warning("TranslationEngine 未初始化，无法将 GUI 实例传递给它。")

            # --- 显示 GUI 窗口 ---
            self.gui.show()
            self.logger.info("GUI 窗口已成功显示。")
        except Exception as e:
            # 处理 UI 初始化失败的情况
            ui_error_msg = f"初始化用户界面失败: {e}"
            self.logger.critical(ui_error_msg, exc_info=True)
            # 抛出 RuntimeError，由外层 __init__ 的 try-except 块捕获
            raise RuntimeError(ui_error_msg) from e

    def process_single_document(self, source_file, settings, worker):
        """
        处理单个文档的完整流程。
        这个方法被后台工作线程 (TranslationWorker) 调用，负责一个文件的校验、
        解析、分块、翻译和保存，并通过 `worker` 对象与 GUI 进行状态和进度通信。

        参数:
            source_file (str): 需要处理的源文件的完整路径。
            settings (dict): 用户在 GUI 上选择的翻译设置字典。
            worker (TranslationWorker): 调用此方法的工作线程实例，用于：
                                        - 发射信号更新 GUI（状态、进度、日志）。
                                        - 检查暂停/取消状态。

        返回:
            bool: True 表示文件处理成功完成（包括成功跳过空文件或无内容文件的情况），
                  False 表示处理过程中发生严重错误（如哈希失败、解析失败、分块失败、
                  翻译过程中遇到不可恢复错误、保存失败）或任务被中止。
        """
        # 获取文件名用于日志
        base_filename = os.path.basename(source_file)
        # --- 记录函数入口信息 ---
        self.logger.info(f"===== 开始处理文件: {base_filename} =====")
        self.logger.debug(f"文件路径: {source_file}")
        self.logger.debug(f"接收到的翻译设置: {settings}")
        # --- 发送 GUI 日志：文件处理开始 ---
        worker.log.emit(f"🚀 开始处理文件: {base_filename}", "info")

        # --- 内部辅助函数：发射文件状态更新信号 ---
        def emit_status(status_code, data=None):
            """安全地发射 file_item_status_update 信号。"""
            # 确保 worker 和信号存在
            if worker and hasattr(worker, 'file_item_status_update'):
                 # 发射信号，传递文件路径、状态码和附加数据
                 worker.file_item_status_update.emit(source_file, status_code, data)
                 self.logger.debug(f"[{base_filename}] 发射状态信号: {status_code}, 数据: {data}")
            else:
                 # 如果无法发射信号，记录警告
                 self.logger.warning(f"[{base_filename}] 无法发射状态信号: Worker 或信号丢失。")

        # --- 内部辅助函数：重置和完成块进度条 ---
        reset_chunk_progress = lambda: worker.chunk_progress.emit(0) if worker else None
        complete_chunk_progress = lambda: worker.chunk_progress.emit(100) if worker else None

        # --- 步骤 1: 初始状态检查和日志 ---
        self.logger.info(f"[{base_filename}] 初始检查和准备...")
        emit_status(STATUS_PROCESSING) # 设置初始状态为“处理中”
        reset_chunk_progress()         # 重置当前文件进度条
        worker.wait_if_paused()        # 检查是否需要暂停

        # --- 步骤 2: 文件验证与哈希 ---
        worker.file_status.emit(f"校验文件: {base_filename}...") # 更新底部状态栏
        self.logger.info(f"[{base_filename}] 检查文件存在性和大小...")
        worker.log.emit(f"🔑 [{base_filename}] 开始文件校验...", "info") # GUI 日志

        # 2a. 检查文件是否存在（虽然 Worker 外部可能已检查，但这里再次确认）
        if not os.path.exists(source_file):
            # 如果文件此时不存在，直接抛出 FileNotFoundError，让 Worker 的主循环捕获处理
            raise FileNotFoundError(f"文件不存在: {source_file}")

        # 2b. 检查文件大小是否为 0
        try:
            file_size = os.path.getsize(source_file)
            self.logger.info(f"[{base_filename}] 文件存在，大小: {file_size} 字节。")
            if file_size == 0:
                 # 如果文件为空，记录日志，更新状态，并成功返回 True (跳过是预期行为)
                 msg = f"文件为空，跳过处理。"
                 worker.log.emit(f"⚠️ [{base_filename}] {msg}", "warning")
                 self.logger.warning(f"[{base_filename}] {msg} (路径: {source_file})")
                 worker.file_status.emit(f"文件为空已跳过: {base_filename}")
                 emit_status(STATUS_SKIPPED_EMPTY) # 发射跳过状态
                 complete_chunk_progress() # 块进度视为完成
                 self.logger.info(f"===== 文件处理结束 (空文件跳过): {base_filename} =====")
                 return True # 成功返回
        except OSError as size_e:
            # 如果获取文件大小失败（例如权限问题），记录错误，更新状态，并返回 False
            msg = f"无法获取文件大小，跳过处理: {size_e}"
            worker.log.emit(f"❌ [{base_filename}] {msg}", "error")
            self.logger.error(f"[{base_filename}] {msg} (路径: {source_file})", exc_info=True)
            worker.file_status.emit(f"无法访问已跳过: {base_filename}")
            emit_status(STATUS_ERROR_HASH, f"获取大小失败: {size_e}") # 归类为哈希前错误
            reset_chunk_progress()
            self.logger.info(f"===== 文件处理结束 (获取大小失败): {base_filename} =====")
            return False # 失败返回

        # 2c. 计算文件哈希
        worker.wait_if_paused() # 检查暂停
        worker.file_status.emit(f"计算文件哈希: {base_filename}...") # 更新状态栏
        self.logger.info(f"[{base_filename}] 计算文件 MD5 哈希值...")
        emit_status(STATUS_HASHING) # 设置状态为“校验中”
        try:
            file_hash = get_file_hash(source_file) # 调用哈希函数，内部有日志
            self.logger.info(f"[{base_filename}] 文件哈希计算成功: {file_hash}")
            worker.log.emit(f"🔑 [{base_filename}] 文件校验成功 (哈希: {file_hash[:8]}...)。", "info") # GUI 日志
        except Exception as hash_e:
             # 如果哈希计算失败，记录错误，更新状态，并返回 False
             msg = f"计算文件哈希失败: {hash_e}"
             worker.log.emit(f"❌ [{base_filename}] {msg}，跳过。", "error")
             self.logger.error(f"[{base_filename}] {msg} (路径: {source_file})", exc_info=True)
             worker.file_status.emit(f"哈希计算失败已跳过: {base_filename}")
             emit_status(STATUS_ERROR_HASH, str(hash_e)) # 发射错误状态
             reset_chunk_progress()
             self.logger.info(f"===== 文件处理结束 (哈希失败): {base_filename} =====")
             return False # 失败返回

        # --- 步骤 3: 提取文本 ---
        self.logger.info(f"[{base_filename}] 提取文件内容...")
        worker.wait_if_paused() # 检查暂停
        worker.file_status.emit(f"正在解析: {base_filename}...") # 更新状态栏
        emit_status(STATUS_PARSING) # 设置状态为“解析中”
        worker.log.emit(f"📄 [{base_filename}] 开始解析文件内容...", "info") # GUI 日志
        original_content = None
        try:
            self.logger.info(f"[{base_filename}] 调用内容提取函数...")
            # 调用内部辅助函数根据文件类型提取内容
            original_content = self._extract_file_content(source_file, worker) # 辅助函数内部有日志和暂停检查
            # 如果辅助函数返回 None，表示提取失败
            if original_content is None:
                worker.file_status.emit(f"内容提取失败已跳过: {base_filename}")
                emit_status(STATUS_ERROR_PARSE, "提取函数返回 None") # 发射特定错误状态
                reset_chunk_progress()
                self.logger.info(f"===== 文件处理结束 (提取失败): {base_filename} =====")
                return False # 失败返回
            # 提取成功
            self.logger.info(f"[{base_filename}] 文件内容提取成功。")
            # 描述提取内容的大小（段落数或字符数）
            content_desc = f"{len(original_content)} 段/行" if isinstance(original_content, list) else f"{len(original_content)} 字符"
            worker.log.emit(f"📄 [{base_filename}] 文件内容解析成功 ({content_desc})。", "success") # GUI 日志
        except Exception as extract_e:
            # 捕获 _extract_file_content 可能抛出的其他未预料异常
            msg = f"解析文件时发生意外错误: {extract_e}"
            worker.log.emit(f"❌ [{base_filename}] {msg}，跳过。", "error")
            self.logger.error(f"[{base_filename}] {msg} (路径: {source_file})", exc_info=True)
            worker.file_status.emit(f"解析失败已跳过: {base_filename}")
            emit_status(STATUS_ERROR_PARSE, str(extract_e)) # 发射错误状态
            reset_chunk_progress()
            self.logger.info(f"===== 文件处理结束 (意外解析错误): {base_filename} =====")
            return False # 失败返回

        # --- 步骤 4: 准备翻译参数 ---
        self.logger.info(f"[{base_filename}] 准备翻译参数...")
        worker.wait_if_paused() # 检查暂停
        # 4a. 获取目标语言代码
        target_lang_name = settings['-LANG-']
        target_lang_code = self.engine.language_map.get(target_lang_name)
        if not target_lang_code: # 如果语言名称无效
             config_err_msg = f"无效的目标语言名称配置: {target_lang_name}"
             self.logger.error(f"[{base_filename}] {config_err_msg}")
             reset_chunk_progress()
             # 抛出 ValueError，让 Worker 主循环捕获并中止任务
             raise ValueError(config_err_msg)

        # 4b. 获取风格代码或自定义提示词
        style_name = settings['-STYLE-']
        style_code_or_prompt = self.engine.style_map.get(style_name)
        if style_name == "通用": # 如果是自定义风格
            style_code_or_prompt = settings.get('-CUSTOM_PROMPT-', "").strip()
            if not style_code_or_prompt: # 如果用户没有提供提示词
                 msg = "'通用'风格未提供自定义提示词，将回退使用'标准'风格。"
                 worker.log.emit(f"⚠️ [{base_filename}] {msg}", "warning") # GUI 日志
                 self.logger.warning(f"[{base_filename}] {msg}") # 文件日志
                 # 回退到标准风格
                 style_code_or_prompt = self.engine.style_map.get("标准", "standard")
            else: # 如果提供了自定义提示词
                 self.logger.info(f"[{base_filename}] 使用用户提供的自定义提示词。")
        elif style_code_or_prompt is None: # 如果风格名称无效
             msg = f"未知的翻译风格 '{style_name}'，将回退使用'标准'风格。"
             worker.log.emit(f"⚠️ [{base_filename}] {msg}", "warning") # GUI 日志
             self.logger.warning(f"[{base_filename}] {msg}") # 文件日志
             # 回退到标准风格
             style_code_or_prompt = self.engine.style_map.get("标准", "standard")
        else: # 如果是有效的预设风格
            self.logger.info(f"[{base_filename}] 使用预设风格: {style_name} ({style_code_or_prompt})")

        # 4c. 获取并验证温度值
        try:
            temp = float(settings['-TEMP-']) # 转换为浮点数
            assert 0 <= temp <= 2 # 验证范围
            self.logger.info(f"[{base_filename}] 使用温度值: {temp}")
        except (ValueError, AssertionError): # 处理无效值
            config_err_msg = f"无效的温度值配置: {settings['-TEMP-']}，请输入 0 到 2 之间的数字。"
            self.logger.error(f"[{base_filename}] {config_err_msg}")
            reset_chunk_progress()
            # 抛出 ValueError，让 Worker 主循环捕获
            raise ValueError(config_err_msg) from None

        # 4d. 获取模型名称
        model_name = settings['-MODEL-']
        self.logger.info(f"[{base_filename}] 使用模型: {model_name}")
        # --- 发送 GUI 日志：参数准备完成 ---
        worker.log.emit(f"⚙️ [{base_filename}] 翻译参数准备就绪 (语言: {target_lang_name}, 风格: {style_name}, 模型: {model_name})。", "info")

        # --- 步骤 5: 动态分块 ---
        self.logger.info(f"[{base_filename}] 执行动态分块...")
        worker.wait_if_paused() # 检查暂停
        worker.file_status.emit(f"智能分块: {base_filename}...") # 更新状态栏
        emit_status(STATUS_SPLITTING) # 设置状态为“分块中”
        worker.log.emit(f"✂️ [{base_filename}] 正在进行智能分块...", "info") # GUI 日志

        # 确保 original_content 是列表类型
        if isinstance(original_content, str):
            original_content = original_content.splitlines(keepends=True)
            self.logger.debug(f"[{base_filename}] 输入内容是字符串，已按行分割。")
        elif not isinstance(original_content, list):
             # 如果内容类型不正确，记录错误并返回 False
             type_err_msg = f"无法处理的原始内容类型: {type(original_content)}，应为 list 或 str。"
             self.logger.error(f"[{base_filename}] {type_err_msg}")
             reset_chunk_progress()
             emit_status(STATUS_ERROR_SPLIT, type_err_msg) # 发射错误状态
             self.logger.info(f"===== 文件处理结束 (分块输入类型错误): {base_filename} =====")
             return False # 失败返回

        # 5a. 检查提取内容是否为空（去除空白行后）
        self.logger.info(f"[{base_filename}] 检查提取内容是否为空...")
        if not any(line.strip() for line in original_content):
            # 如果内容为空，记录日志，更新状态，并成功返回 True
            msg = f"文件内容（去除空白后）为空，跳过翻译和保存。"
            worker.log.emit(f"⚠️ [{base_filename}] {msg}", "warning")
            self.logger.warning(f"[{base_filename}] {msg} (路径: {source_file})")
            worker.file_status.emit(f"内容为空已跳过: {base_filename}")
            emit_status(STATUS_SKIPPED_NO_CONTENT) # 发射特定跳过状态
            complete_chunk_progress() # 块进度视为完成
            self.logger.info(f"===== 文件处理结束 (内容为空跳过): {base_filename} =====")
            return True # 成功返回

        self.logger.info(f"[{base_filename}] 内容非空，继续执行分块。")

        # 5b. 执行分块
        chunks = []
        try:
            # 获取默认分块大小配置
            max_tokens = FILE_HANDLER_CONFIG["CHUNKING"]["DEFAULT_MAX_TOKENS"]
            self.logger.info(f"[{base_filename}] 调用 dynamic_split，目标语言: {target_lang_code}, 最大长度: {max_tokens} 字节...")
            # 调用分块函数，内部有详细日志
            chunks = dynamic_split(original_content, target_lang_code, max_tokens=max_tokens)
            # 检查分块结果是否为空
            if not chunks or not any(chunk.strip() for chunk in chunks):
                 # 如果分块后结果为空，记录日志，更新状态，并成功返回 True
                 msg = f"文件分块后内容为空，跳过翻译和保存。"
                 worker.log.emit(f"⚠️ [{base_filename}] {msg}", "warning")
                 self.logger.warning(f"[{base_filename}] {msg} (路径: {source_file})")
                 worker.file_status.emit(f"分块失败已跳过: {base_filename}")
                 emit_status(STATUS_SKIPPED_NO_CONTENT) # 发射特定跳过状态
                 complete_chunk_progress()
                 self.logger.info(f"===== 文件处理结束 (分块后为空跳过): {base_filename} =====")
                 return True # 成功返回
            # 分块成功且结果非空
            self.logger.info(f"[{base_filename}] 智能分块完成，生成 {len(chunks)} 个块。")
            worker.log.emit(f"✅ [{base_filename}] 智能分块完成，共 {len(chunks)} 块。", "success") # GUI 日志
        except Exception as split_e:
             # 如果分块过程中发生错误，记录日志，更新状态，并返回 False
             msg = f"文件分块时出错: {split_e}"
             worker.log.emit(f"❌ [{base_filename}] {msg}，跳过。", "error")
             self.logger.error(f"[{base_filename}] {msg} (路径: {source_file})", exc_info=True)
             worker.file_status.emit(f"分块失败已跳过: {base_filename}")
             emit_status(STATUS_ERROR_SPLIT, str(split_e)) # 发射错误状态
             reset_chunk_progress()
             self.logger.info(f"===== 文件处理结束 (分块失败): {base_filename} =====")
             return False # 失败返回

        # --- 步骤 6: 逐块执行翻译 ---
        self.logger.info(f"[{base_filename}] 逐块执行翻译 (共 {len(chunks)} 块)")
        translated_chunks = [] # 存储翻译后的块
        previous_chunk_context = "" # 上下文内容
        current_model = model_name # 当前使用的模型（可能因重试而改变）
        translation_successful_overall = True # 标记整个文件翻译是否成功（无严重错误）
        has_failed_chunks = False           # 标记是否有非严重的块翻译失败（例如返回空）
        total_chunks = len(chunks)          # 总块数

        self.logger.info(f"[{base_filename}] 准备开始翻译循环...")
        worker.log.emit(f"💬 [{base_filename}] 开始翻译 {total_chunks} 个文本块...", "info") # GUI 日志
        try: # 使用 try...finally 确保块进度条最终能正确设置
            # 遍历所有文本块
            for i, chunk in enumerate(chunks):
                current_chunk_index = i + 1 # 当前块号（从 1 开始）
                self.logger.info(f"[{base_filename}] 开始处理块 {current_chunk_index}/{total_chunks}")
                worker.wait_if_paused() # 检查暂停
                QApplication.processEvents() # 处理 GUI 事件

                # 更新状态栏和文件列表项状态
                progress_text = f"块 {current_chunk_index}/{total_chunks}"
                worker.file_status.emit(f"翻译中: {base_filename} ({progress_text})")
                emit_status(STATUS_TRANSLATING, {"current": current_chunk_index, "total": total_chunks})
                worker.log.emit(f"➡️ [{base_filename}] 开始翻译块 {current_chunk_index}/{total_chunks}...", "info") # GUI 日志

                translated = None      # 存储当前块的翻译结果
                model_used = current_model # 记录实际使用的模型

                # 如果当前块内容为空（去除空白后），则跳过翻译
                if not chunk.strip():
                    self.logger.info(f"[{base_filename}] 块 {current_chunk_index} 内容为空，跳过翻译。")
                    worker.log.emit(f"⚪ [{base_filename}] 块 {current_chunk_index}/{total_chunks} 为空，已跳过。", "info") # GUI 日志
                    translated_chunks.append("") # 添加空字符串占位
                    # 更新块进度条
                    chunk_progress_value = int((current_chunk_index / total_chunks) * 100) if total_chunks > 0 else 0
                    worker.chunk_progress.emit(chunk_progress_value)
                    continue # 处理下一个块

                # 调用翻译引擎进行翻译
                self.logger.info(f"[{base_filename}] 调用翻译引擎处理块 {current_chunk_index}...")
                try:
                    # 调用 safe_translate，它包含了重试、错误处理和缓存逻辑
                    # 并将 GUI 日志回调函数传递给它，以便在引擎内部发送日志
                    translated, model_used = self.engine.safe_translate(
                        text=chunk, target_lang_code=target_lang_code, style_code_or_prompt=style_code_or_prompt,
                        temp=temp, model_name=current_model, file_hash=file_hash,
                        previous_chunk=previous_chunk_context,
                        # 使用 lambda 创建一个包装函数，在消息前添加文件名和块号信息
                        log_callback=lambda msg, type="info": worker.log.emit(f"   [{base_filename}|块 {current_chunk_index}] {msg}", type),
                        worker=worker # 传递 worker 用于暂停检查
                    )
                    self.logger.info(f"[{base_filename}] 块 {current_chunk_index} 翻译引擎调用完成。")

                    # 检查模型是否在重试中被切换
                    if model_used != current_model:
                        model_change_msg = f"模型已从 {current_model} 自动切换到 {model_used}"
                        worker.log.emit(f"⚠️ [{base_filename}] {model_change_msg} (块 {current_chunk_index})", "warning") # GUI 日志
                        self.logger.warning(f"[{base_filename}] {model_change_msg} (块 {current_chunk_index})") # 文件日志
                        current_model = model_used # 更新当前模型

                    # --- 处理翻译结果 ---
                    # 检查翻译结果是否为空（可能由 safe_translate 在重试耗尽后返回）
                    if translated is None or translated == "":
                        fail_msg = f"块 {current_chunk_index} 翻译失败或返回空结果。"
                        worker.log.emit(f"❌ [{base_filename}] {fail_msg}", "error") # GUI 日志
                        self.logger.warning(f"[{base_filename}] {fail_msg}") # 文件日志
                        # 添加失败标记到结果列表，以便后续识别
                        translated_chunks.append(f"[块 {current_chunk_index} 翻译失败或为空]\n")
                        has_failed_chunks = True # 标记存在失败的块
                    else:
                        # 翻译成功
                        worker.log.emit(f"✅ [{base_filename}] 块 {current_chunk_index}/{total_chunks} 翻译成功。", "success") # GUI 日志
                        self.logger.info(f"[{base_filename}] 块 {current_chunk_index} 翻译成功。")
                        translated_chunks.append(translated) # 添加到结果列表
                        # 更新块进度条
                        chunk_progress_value = int((current_chunk_index / total_chunks) * 100) if total_chunks > 0 else 0
                        worker.chunk_progress.emit(chunk_progress_value)
                        self.logger.debug(f"[{base_filename}] 块进度更新为: {chunk_progress_value}%")
                    # --- 结束处理翻译结果 ---

                    # --- 更新上下文 ---
                    # 获取当前块的末尾部分作为下一个块的上下文
                    context_length = TRANSLATION_CONFIG["CONTEXT_LENGTH"].get(target_lang_code, 300)
                    if chunk.strip(): # 仅当块非空时更新上下文
                        previous_chunk_context = chunk[-context_length:]
                        self.logger.debug(f"[{base_filename}] 更新上下文为块 {current_chunk_index} 的末尾 {context_length} 字符。")

                # --- 处理翻译过程中不可重试的严重错误 ---
                except (PermissionError, ValueError) as critical_error:
                    error_msg = str(critical_error)
                    full_error_msg = f"严重错误导致文件处理中止: {error_msg}"
                    worker.log.emit(f"❌ [{base_filename}] {full_error_msg}", "error") # GUI 日志
                    self.logger.critical(f"[{base_filename}] {full_error_msg} (块 {current_chunk_index})", exc_info=False) # 文件日志
                    worker.file_status.emit(f"严重错误已中止: {base_filename}") # 更新状态栏
                    emit_status(STATUS_ERROR_CRITICAL, error_msg) # 发射严重错误状态
                    translation_successful_overall = False # 标记整体失败
                    break # 中断翻译循环

                # --- 处理翻译过程中其他未预料的错误 ---
                except Exception as unexpected_trans_error:
                    error_msg = str(unexpected_trans_error)
                    full_error_msg = f"翻译块时发生意外错误，中止文件处理: {error_msg}"
                    worker.log.emit(f"❌ [{base_filename}] {full_error_msg}", "error") # GUI 日志
                    self.logger.error(f"[{base_filename}] {full_error_msg} (块 {current_chunk_index})", exc_info=True) # 文件日志
                    worker.file_status.emit(f"翻译错误已中止: {base_filename}") # 更新状态栏
                    emit_status(STATUS_ERROR_CRITICAL, f"意外错误: {error_msg}") # 发射严重错误状态
                    translation_successful_overall = False # 标记整体失败
                    break # 中断翻译循环
                # --- 结束单个块的处理 ---
            # --- 结束翻译循环 ---
            self.logger.info(f"[{base_filename}] 翻译循环处理完毕。")

        finally: # 无论循环如何结束
            # 如果是因为严重错误中止，重置块进度条
            if not translation_successful_overall:
                self.logger.warning(f"[{base_filename}] 由于发生致命错误，翻译循环提前中止，重置块进度。")
                reset_chunk_progress()
            # 如果是正常结束或只有非严重失败，将块进度设置为 100%
            else:
                self.logger.info(f"[{base_filename}] 翻译循环正常结束，设置块进度为 100%。")
                complete_chunk_progress()

        # --- 步骤 7: 检查整体结果 ---
        self.logger.info(f"[{base_filename}] 检查整体翻译结果...")
        # 如果在翻译循环中标记了严重失败，则直接返回 False
        if not translation_successful_overall:
             self.logger.warning(f"[{base_filename}] 由于发生严重错误，处理已中止，不进行保存。")
             worker.log.emit(f"🛑 [{base_filename}] 因严重错误中止，未保存。", "error") # GUI 日志
             self.logger.info(f"===== 文件处理结束 (严重错误中止): {base_filename} =====")
             return False # 失败返回

        # 检查是否有任何有效的翻译内容（非空且不是失败标记）
        self.logger.info(f"[{base_filename}] 检查是否存在有效翻译内容...")
        has_valid_content = any(t.strip() and not t.startswith("[块 ") for t in translated_chunks)
        if not has_valid_content:
             # 如果所有块都失败或返回空，记录错误，更新状态，并返回 False
             msg = f"所有块翻译失败或结果为空，跳过保存。"
             worker.log.emit(f"❌ [{base_filename}] {msg}", "error") # GUI 日志
             self.logger.error(f"[{base_filename}] {msg} (路径: {source_file})") # 文件日志
             worker.file_status.emit(f"翻译失败已跳过: {base_filename}") # 更新状态栏
             emit_status(STATUS_ERROR_TRANSLATE, "所有块失败或结果为空") # 发射翻译错误状态
             self.logger.info(f"===== 文件处理结束 (无有效翻译结果): {base_filename} =====")
             return False # 失败返回
        self.logger.info(f"[{base_filename}] 存在有效翻译内容。")

        # --- 步骤 8: 合并与保存 ---
        self.logger.info(f"[{base_filename}] 合并与保存结果...")
        worker.file_status.emit(f"合并翻译结果: {base_filename}...") # 更新状态栏
        worker.log.emit(f"➕ [{base_filename}] 开始合并翻译结果...", "info") # GUI 日志
        # 使用换行符连接所有翻译后的块
        final_translated_content = "\n".join(translated_chunks)
        self.logger.info(f"[{base_filename}] 所有翻译块已合并。")
        worker.log.emit(f"✅ [{base_filename}] 翻译结果合并完成。", "success") # GUI 日志

        worker.wait_if_paused() # 检查暂停
        final_output_path = "" # 初始化输出路径变量
        try:
            # 8a. 生成输出文件路径
            self.logger.info(f"[{base_filename}] 生成输出文件路径...")
            # 调用内部辅助函数生成基础路径和文件名
            output_dir, base_filename_part = self._generate_output_base_path(source_file, settings)
            # 添加时间戳和后缀
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = '.docx' if settings['-WORD-'] else '.txt'
            final_output_path = os.path.join(output_dir, f"{base_filename_part}_{timestamp}{ext}")
            self.logger.info(f"[{base_filename}] 最终输出路径确定: {final_output_path}")

            # 8b. 保存文件
            worker.file_status.emit(f"正在保存到: {os.path.basename(final_output_path)}...") # 更新状态栏
            emit_status(STATUS_SAVING) # 设置状态为“保存中”
            worker.log.emit(f"💾 [{base_filename}] 开始保存结果到 {os.path.basename(final_output_path)}...", "info") # GUI 日志

            # 调用内部辅助函数进行保存
            self._save_result(settings, final_translated_content, final_output_path) # 内部有日志

            # --- 处理保存成功后的日志 ---
            save_log_msg_base = f"结果已成功保存到: {os.path.basename(final_output_path)}"
            # 检查之前是否有失败的块
            if has_failed_chunks:
                # 如果有失败块，日志消息添加警告，类型设为 warning
                save_log_msg = f"{save_log_msg_base} (注意: 部分块翻译失败或为空)"
                save_msg_type = "warning"
                self.logger.warning(f"[{base_filename}] 文件保存完成，但包含失败或空的块。")
            else:
                # 如果全部成功，使用基础消息，类型设为 success
                save_log_msg = save_log_msg_base
                save_msg_type = "success"
                self.logger.info(f"[{base_filename}] 文件保存成功完成。")
            # 发送 GUI 日志
            worker.log.emit(f"✅ [{base_filename}] {save_log_msg}", save_msg_type)

        except Exception as save_e:
             # 如果保存过程中发生错误，记录日志，更新状态，并返回 False
             msg = f"保存文件时出错: {save_e}"
             worker.log.emit(f"❌ [{base_filename}] {msg}，文件处理中止。", "error") # GUI 日志
             self.logger.error(f"[{base_filename}] {msg} (尝试保存到: {final_output_path or '路径未确定'})", exc_info=True) # 文件日志
             worker.file_status.emit(f"保存失败已中止: {base_filename}") # 更新状态栏
             emit_status(STATUS_ERROR_SAVE, str(save_e)) # 发射保存错误状态
             reset_chunk_progress()
             self.logger.info(f"===== 文件处理结束 (保存失败): {base_filename} =====")
             return False # 失败返回

        # --- 步骤 9: 完成 ---
        self.logger.info(f"[{base_filename}] 处理完成。")
        # 根据是否有失败块确定最终状态码
        final_status_code = STATUS_COMPLETED_OK if not has_failed_chunks else STATUS_COMPLETED_WARN
        status_msg = "处理成功" if final_status_code == STATUS_COMPLETED_OK else "处理完成(含警告)"
        worker.file_status.emit(f"{status_msg}: {base_filename}") # 更新状态栏
        emit_status(final_status_code) # 发射最终状态
        # --- 发送 GUI 日志：文件处理完成 ---
        completion_icon = "🎉" if final_status_code == STATUS_COMPLETED_OK else "🏁" # 选择图标
        completion_type = "success" if final_status_code == STATUS_COMPLETED_OK else "info" # 选择消息类型
        worker.log.emit(f"{completion_icon} [{base_filename}] 文件处理流程结束。", completion_type) # GUI 日志
        self.logger.info(f"===== 文件处理成功结束 ({'含警告' if has_failed_chunks else '无警告'}): {base_filename} =====")
        # 返回 True 表示成功处理此文件
        return True
    # --- 结束 process_single_document ---

    # --- 内部辅助方法 ---
    def _extract_file_content(self, file_path, worker):
        """
        根据文件扩展名调用相应的文本提取函数。
        包含了对暂停状态的检查。

        参数:
            file_path (str): 文件的完整路径。
            worker (TranslationWorker): 工作线程实例，用于检查暂停。

        返回:
            list[str] or str or None: 提取到的文本内容（列表或字符串），如果不支持或提取失败则返回 None。

        异常:
            可能会重新抛出底层提取函数 (extract_text_from_docx, extract_text_from_txt) 抛出的异常。
        """
        worker.wait_if_paused() # 检查暂停状态
        base_filename = os.path.basename(file_path) # 获取文件名
        # 获取文件扩展名并转为小写
        file_ext = os.path.splitext(file_path)[1].lower()
        self.logger.info(f"[{base_filename}] 开始提取内容，文件类型: {file_ext}")

        try:
            content = None
            # 根据扩展名选择提取函数
            if file_ext == '.docx':
                self.logger.debug(f"[{base_filename}] 使用 DOCX 提取器...")
                # 调用 DOCX 提取函数，内部有日志
                content = extract_text_from_docx(file_path)
                self.logger.info(f"[{base_filename}] DOCX 内容提取完成。")
            elif file_ext == '.txt':
                self.logger.debug(f"[{base_filename}] 使用 TXT 提取器...")
                # 调用 TXT 提取函数，内部有日志和编码检测
                content = extract_text_from_txt(file_path)
                self.logger.info(f"[{base_filename}] TXT 内容提取完成。")
            else:
                # 如果是不支持的格式
                msg = f"不支持的文件格式: {file_ext}"
                self.logger.error(f"[{base_filename}] {msg} (路径: {file_path})")
                worker.log.emit(f"❌ [{base_filename}] {msg}，跳过。", "error") # GUI 日志
                return None # 返回 None 表示提取失败

            worker.wait_if_paused() # 再次检查暂停
            # 记录提取结果的类型和大小（用于调试）
            if isinstance(content, list):
                 self.logger.debug(f"[{base_filename}] 提取到 {len(content)} 个段落/行。")
            elif isinstance(content, str):
                 self.logger.debug(f"[{base_filename}] 提取到文本，长度 {len(content)} 字符。")
            # 返回提取到的内容
            return content

        except Exception as e:
            # 捕获提取过程中可能发生的其他错误
            msg = f"读取或解析文件时出错: {e}"
            self.logger.error(f"[{base_filename}] {msg} (路径: {file_path})", exc_info=True) # 文件日志
            worker.log.emit(f"❌ [{base_filename}] {msg}，跳过。", "error") # GUI 日志
            return None # 返回 None 表示提取失败

    def _save_result(self, settings, translated_content, output_path):
        """
        根据用户设置将翻译后的内容保存到文件。

        参数:
            settings (dict): 包含输出格式 ('-WORD-') 的设置字典。
            translated_content (str): 包含所有翻译块（用 \n 连接）的完整字符串。
            output_path (str): 最终输出文件的完整路径。

        异常:
            IOError: 如果无法创建输出目录或写入文件失败。
            可能会重新抛出底层保存函数 (save_as_word, save_as_txt) 抛出的异常。
        """
        # 获取输出文件名用于日志
        base_filename = os.path.basename(output_path)
        self.logger.info(f"[{base_filename}] 开始保存翻译结果...")
        self.logger.debug(f"[{base_filename}] 保存路径: {output_path}")
        # 判断输出格式
        output_format = "Word (DOCX)" if settings['-WORD-'] else "Text (TXT)"
        self.logger.debug(f"[{base_filename}] 保存格式: {output_format}")

        # --- 检查并创建输出目录 ---
        output_dir = os.path.dirname(output_path)
        if not os.path.exists(output_dir):
             try:
                 self.logger.warning(f"[{base_filename}] 输出目录不存在，尝试创建: {output_dir}")
                 os.makedirs(output_dir) # 创建目录
                 self.logger.info(f"[{base_filename}] 输出目录创建成功: {output_dir}")
             except OSError as e: # 处理创建失败
                  dir_error_msg = f"无法创建输出目录 {output_dir}: {e}"
                  self.logger.error(f"[{base_filename}] {dir_error_msg}", exc_info=True)
                  raise IOError(dir_error_msg) from e # 抛出 IO 错误

        try:
            # --- 准备内容列表 ---
            # 保存函数通常期望接收一个字符串列表（代表段落或行）
            # 这里将包含所有块的字符串按行分割
            content_list_for_saving = translated_content.splitlines()
            self.logger.debug(f"[{base_filename}] 准备调用保存函数，共 {len(content_list_for_saving)} 行。")

            # --- 调用相应的保存函数 ---
            if settings['-WORD-']: # 如果是 Word 格式
                save_as_word(content_list_for_saving, output_path) # 内部有日志
            else: # 如果是 TXT 格式
                save_as_txt(content_list_for_saving, output_path) # 内部有日志

            # 获取保存后的文件大小
            final_size = os.path.getsize(output_path)
            self.logger.info(f"[{base_filename}] 翻译结果保存成功 | 大小: {final_size} 字节")
        except Exception as e:
            # 处理保存过程中可能发生的错误
            save_error_msg = f"文件保存失败: {e}"
            self.logger.error(f"[{base_filename}] {save_error_msg} (路径: {output_path})", exc_info=True) # 文件日志
            raise IOError(save_error_msg) from e # 抛出 IO 错误

    def _generate_output_base_path(self, source_file, settings):
        """
        生成输出文件的基础部分（不含时间戳和扩展名）。
        格式通常是：[原文件名]_translated_[语言代码]

        参数:
            source_file (str): 源文件的完整路径。
            settings (dict): 包含目标语言 ('-LANG-') 和输出目录 ('-OUTPUT-') 的设置字典。

        返回:
            tuple[str, str]: 一个包含两个元素的元组：
                - str: 输出目录的路径。
                - str: 生成的基础文件名部分。
        """
        output_dir = settings['-OUTPUT-'] # 获取输出目录
        # 获取源文件名（不含扩展名）
        base_name = os.path.splitext(os.path.basename(source_file))[0]
        # 获取目标语言名称和代码
        target_lang_name = settings['-LANG-']
        target_lang_code = self.engine.language_map.get(target_lang_name, 'unk') # 提供默认值 'unk'
        # 构建基础文件名
        generated_base = f"{base_name}_translated_{target_lang_code}"
        self.logger.debug(f"[{os.path.basename(source_file)}] 生成的基础输出名: {generated_base}, 目录: {output_dir}")
        # 返回输出目录和基础文件名
        return output_dir, generated_base
    # --- 结束内部辅助方法 ---

    # --- 启动应用程序 ---
    def run(self):
        """启动 Qt 应用程序的主事件循环。"""
        # 检查 QApplication 是否已初始化
        if not self.qt_app:
             self.logger.critical("QApplication 未初始化，无法启动事件循环。应用程序将退出。")
             sys.exit(1) # 退出
        # 记录事件循环启动
        self.logger.info("==============================================")
        self.logger.info("       启动应用程序主事件循环        ")
        self.logger.info("==============================================")
        # 执行 Qt 事件循环，这将阻塞直到应用程序退出
        exit_code = self.qt_app.exec()
        # 记录事件循环结束和退出码
        self.logger.info("----------------------------------------------")
        self.logger.info(f"       应用程序事件循环结束 (退出码: {exit_code})       ")
        self.logger.info("----------------------------------------------")
        # 使用 Qt 返回的退出码退出 Python 进程
        sys.exit(exit_code)
# --- 结束 Application 类 ---


# --- 程序主入口 ---
if __name__ == "__main__":
    # --- 步骤 1: 设置日志记录 ---
    # 必须在创建 Application 实例之前调用，因为初始化过程需要日志
    setup_logging()
    main_logger = logging.getLogger("main") # 获取主记录器
    app_instance = None # 初始化应用实例变量
    exit_code = 0 # 默认退出码

    try:
        # --- 步骤 2: 创建 Application 实例 ---
        main_logger.info("主程序入口 (__main__)：开始创建 Application 实例...")
        # 创建 Application 实例，其 __init__ 方法会执行所有初始化步骤
        app_instance = Application()
        main_logger.info("主程序入口 (__main__)：Application 实例创建完成，调用 run() 启动事件循环...")
        # --- 步骤 3: 运行应用程序 ---
        # 调用 run 方法启动 Qt 事件循环，程序将在此阻塞直到退出
        app_instance.run() # run() 内部会调用 sys.exit()，正常情况下这里不会执行到

    except SystemExit as e:
         # 捕获由 sys.exit() 引发的退出（包括 run() 方法内部的退出）
         main_logger.info(f"主程序入口 (__main__)：应用程序通过 SystemExit 正常退出 (代码: {e.code})")
         exit_code = e.code # 获取退出码
    except Exception as main_exc:
         # 捕获在主流程中（主要是 Application 初始化之外）发生的未处理异常
         main_logger.critical("主程序入口 (__main__)：在主执行流程中遇到无法处理的严重错误。", exc_info=True)
         exit_code = 1 # 设置错误退出码
         # 尝试弹出最终的错误消息框
         try:
             # 尝试获取或创建 QApplication 实例
             app = QApplication.instance()
             if app is None:
                 main_logger.warning("无法获取 QApplication 实例，尝试创建临时实例显示错误。")
                 app = QApplication(sys.argv)
             # 显示错误消息
             QMessageBox.critical(None, "致命错误", f"应用程序意外终止。\n请查看日志文件了解详情。\n错误: {main_exc}")
             main_logger.info("致命错误消息已成功显示给用户。")
         except Exception as mb_exc: # 处理显示消息框时的错误
             error_log = f"FATAL ERROR in __main__: {main_exc}\nCould not display error message box: {mb_exc}"
             main_logger.critical(error_log)
             print(error_log, file=sys.stderr) # 打印到 stderr
    finally:
         # --- 步骤 4: 清理和退出 ---
         main_logger.info(f"主程序入口 (__main__)：应用程序即将退出，最终退出码: {exit_code}")
         # 关闭日志系统，确保所有缓冲的日志都被写入文件
         logging.shutdown()
         # 以最终确定的退出码退出程序
         sys.exit(exit_code)
# --- 结束程序主入口 ---