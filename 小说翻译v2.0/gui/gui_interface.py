# gui/gui_interface.py
"""
图形用户界面 (GUI) 模块 (gui_interface.py)

功能：
该模块使用 PyQt6 构建应用程序的主用户界面。它提供了用户与翻译功能交互的窗口，
管理文件队列、翻译参数配置、任务启动与控制（暂停/恢复/取消）、进度显示以及实时日志反馈。

核心机制：
- 基于 PyQt6 的窗口和控件实现。
- 使用 QThread 和 QObject 实现多线程，将耗时的翻译任务放在后台执行，避免界面冻结。
- 通过信号 (pyqtSignal) 和槽 (slot) 机制实现主线程 (GUI) 与工作线程之间的安全通信。
- 提供文件拖放功能 (DropListWidget) 和文件列表项的内部排序。
- 动态显示每个文件在处理过程中的详细状态（如待处理、解析中、翻译中、完成、错误等）。
- 集成并调用其他模块的功能（如 config_manager, cache_manager, file_handler, translation_engine）。
- 应用自定义的样式和布局配置 (来自 gui_config.py 和 settings.py)。
- 提供 API 连接测试功能。
- 管理缓存清除操作（全部或选中）。
"""

# 导入 os 模块，用于处理文件路径（获取文件名、目录操作等）。
import os
# 导入 logging 模块，用于记录 GUI 操作和工作线程的日志。
import logging
# 导入 threading 模块，主要用于工作线程中的暂停/恢复逻辑 (Condition)。
import threading
# 导入 pathlib 模块中的 Path 类，用于更方便地处理文件路径。
from pathlib import Path

# --- PyQt6 导入 ---
# 从 PyQt6.QtWidgets 导入 GUI 控件和布局类
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, # 窗口、基础控件、布局
    QFileDialog, QProgressBar, QMessageBox, QTextEdit, QLabel, # 对话框、进度条、消息框、文本编辑、标签
    QLineEdit, QPushButton, QRadioButton, QComboBox, # 输入框、按钮、单选按钮、下拉框
    QGroupBox, QFormLayout, QSizePolicy, QSpacerItem, # 分组框、表单布局、尺寸策略、空白项
    QListWidget, QListWidgetItem, QApplication, QAbstractItemView # 列表控件、列表项、应用程序对象、视图基类
)
# 从 PyQt6.QtCore 导入核心功能类
from PyQt6.QtCore import (
    Qt, pyqtSignal, QObject, QThread, QUrl # 枚举（对齐、光标等）、信号、基础对象、线程、URL处理
)
# 从 PyQt6.QtGui 导入图形界面相关类
from PyQt6.QtGui import (
    QFont, QIcon, QColor, QPalette, QDoubleValidator, QBrush # 字体、图标、颜色、调色板、浮点数验证器、画刷
)
# --- 结束 PyQt6 导入 ---

# --- 项目内部模块导入 ---
# 导入全局配置文件 (GUI颜色、字体, 文件处理配置)
from config.settings import GUI_CONFIG, FILE_HANDLER_CONFIG
# 导入 GUI 特定的配置 (日志类型样式、控件样式、布局参数、图标目录)
from gui.gui_config import (
    LOG_TYPES, STYLES, LAYOUT, ICON_DIR
)
# 导入文件处理器中的哈希函数，用于清除缓存时获取文件标识
from file_processor.file_handler import get_file_hash
# --- 结束项目内部模块导入 ---

# --- 状态码常量定义 ---
# 这些常量字符串用于表示文件在处理过程中的不同状态。
# 与 main.py 中定义的状态码保持一致，便于模块间通信和状态更新。
STATUS_PENDING = "PENDING"              # 待处理
STATUS_PROCESSING = "PROCESSING"        # 正在处理（通用状态）
STATUS_HASHING = "HASHING"              # 正在计算哈希值
STATUS_PARSING = "PARSING"              # 正在解析文件内容
STATUS_SPLITTING = "SPLITTING"          # 正在进行智能分块
STATUS_TRANSLATING = "TRANSLATING"      # 正在调用 API 进行翻译
STATUS_CACHED = "CACHED"                # 翻译结果来自缓存
STATUS_SAVING = "SAVING"                # 正在保存翻译结果
STATUS_COMPLETED_OK = "COMPLETED_OK"    # 处理成功完成
STATUS_COMPLETED_WARN = "COMPLETED_WARN" # 处理完成但有警告（例如部分块失败）
STATUS_SKIPPED_EMPTY = "SKIPPED_EMPTY"  # 因文件为空而跳过
STATUS_SKIPPED_NO_CONTENT = "SKIPPED_NO_CONTENT" # 因文件内容为空（解析/分块后）而跳过
STATUS_ERROR_HASH = "ERROR_HASH"          # 计算哈希时出错
STATUS_ERROR_PARSE = "ERROR_PARSE"        # 解析文件时出错
STATUS_ERROR_SPLIT = "ERROR_SPLIT"        # 分块时出错
STATUS_ERROR_SAVE = "ERROR_SAVE"          # 保存文件时出错
STATUS_ERROR_TRANSLATE = "ERROR_TRANSLATE" # 翻译过程中出错（API调用失败或返回错误）
STATUS_ERROR_CRITICAL = "ERROR_CRITICAL"  # 发生严重错误导致处理中止
STATUS_CANCELLED = "CANCELLED"            # 任务被用户取消
# --- 结束状态码常量定义 ---

# --- 全局变量和初始化 ---
# 从配置中获取颜色字典
COLORS = GUI_CONFIG["COLORS"]
# 为日志和状态补充默认颜色（如果配置中缺失）
if "info" not in COLORS:
    COLORS["info"] = "#2196F3" # 补充普通信息颜色
if "cancel" not in COLORS:
    COLORS["cancel"] = COLORS.get("warning", "#FFC107") # 为取消状态设置颜色（使用警告色或自定义）

# 获取 GUI 模块和工作线程模块的日志记录器实例
gui_logger = logging.getLogger(__name__) # GUI 界面相关日志
worker_logger = logging.getLogger("TranslationWorker") # 后台工作线程相关日志
# --- 结束全局变量和初始化 ---


# --- 自定义 QListWidget ---
class DropListWidget(QListWidget):
    """
    一个继承自 QListWidget 的自定义列表控件。
    增加了对文件和文件夹拖放的支持，并允许用户在列表内部通过拖拽对列表项进行排序。

    信号:
        filesDropped (pyqtSignal(list)): 当有外部文件或文件夹成功拖放到控件上时发射此信号，
                                        参数是包含这些文件/文件夹绝对路径的列表 (list[str])。
    """
    # 定义一个信号，当文件被拖放到列表上时发射
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        """
        初始化 DropListWidget。

        - 调用父类 QListWidget 的构造函数。
        - 设置接受拖放 (`setAcceptDrops(True)`)。
        - 启用交替行颜色 (`setAlternatingRowColors(True)`) 以提高可读性。
        - 设置选择模式为可选择多个项 (`ExtendedSelection`)。
        - 设置拖放模式为内部移动 (`InternalMove`)，允许用户在列表内排序。
        - 显示拖放指示器 (`setDropIndicatorShown(True)`)。
        - 初始化日志记录器。

        参数:
            parent (QWidget, optional): 父控件。默认为 None。
        """
        super().__init__(parent)
        self.setAcceptDrops(True)             # 允许接收拖放事件
        self.setAlternatingRowColors(True)    # 启用交替行背景色
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection) # 允许多选
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove) # 允许内部拖拽排序
        self.setDropIndicatorShown(True)      # 显示拖放位置指示器
        self.logger = logging.getLogger(__name__) # 获取日志记录器
        self.logger.debug("DropListWidget 初始化完成，允许拖放和内部移动。")

    def dragEnterEvent(self, event):
        """
        处理拖拽进入事件。当鼠标拖着对象进入控件区域时被调用。
        决定是否接受该拖拽操作。

        参数:
            event (QDragEnterEvent): 拖拽进入事件对象，包含拖拽数据 (MIME data) 和源信息。
        """
        mime_data = event.mimeData() # 获取拖拽数据
        self.logger.debug(f"dragEnterEvent: Mime types: {mime_data.formats()}, Source: {event.source()}")
        # 检查拖拽的数据是否包含 URL (通常是文件/文件夹) 或者拖拽源是控件本身 (内部排序)
        if mime_data.hasUrls() or event.source() == self:
            # 如果是 URL
            if mime_data.hasUrls():
                # 检查是否是本地文件 URL
                is_local = any(url.isLocalFile() for url in mime_data.urls())
                if is_local:
                    self.logger.debug("dragEnterEvent: 检测到本地文件 URL，接受拖入。")
                    event.acceptProposedAction() # 接受拖拽操作
                else:
                    self.logger.debug("dragEnterEvent: URL 非本地文件，忽略。")
                    event.ignore() # 忽略非本地文件的拖拽
            # 如果是内部排序
            else:
                self.logger.debug("dragEnterEvent: 检测到内部移动，接受。")
                event.acceptProposedAction() # 接受内部排序拖拽
        # 如果既不是 URL 也不是内部排序
        else:
            self.logger.debug("dragEnterEvent: 非支持的拖放源或类型，忽略。")
            event.ignore() # 忽略不支持的拖拽

    def dragMoveEvent(self, event):
        """
        处理拖拽移动事件。当鼠标拖着对象在控件区域内移动时被调用。
        通常用于更新鼠标光标样式或接受/拒绝移动。

        参数:
            event (QDragMoveEvent): 拖拽移动事件对象。
        """
        # 持续接受有效的拖拽移动 (URL 或内部移动)
        if event.mimeData().hasUrls() or event.source() == self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """
        处理放置事件。当用户在控件上释放鼠标按钮完成拖放操作时被调用。

        - 如果是外部文件/文件夹拖放，提取本地文件路径，发射 `filesDropped` 信号。
        - 如果是内部列表项排序，调用父类的 `dropEvent` 处理实际的排序逻辑。

        参数:
            event (QDropEvent): 放置事件对象。
        """
        mime_data = event.mimeData() # 获取放置数据
        self.logger.info("dropEvent: 检测到放置操作。")
        # 检查是否是外部 URL 拖放
        if mime_data.hasUrls():
            urls = mime_data.urls() # 获取 URL 列表
            # 提取所有本地文件路径
            file_paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
            self.logger.info(f"dropEvent: 检测到外部文件拖放，包含 {len(file_paths)} 个本地文件路径。")
            # 如果提取到了有效的文件路径
            if file_paths:
                self.logger.info("dropEvent: 发射 filesDropped 信号...")
                # 发射 filesDropped 信号，将文件路径列表传递出去
                self.filesDropped.emit(file_paths)
                event.acceptProposedAction() # 接受放置操作
                self.logger.debug("dropEvent: 外部文件放置事件已处理并接受。")
                return # 处理完毕，直接返回

        # 如果不是外部文件拖放（即内部排序）
        self.logger.debug("dropEvent: 非外部文件放置，调用基类 dropEvent 处理内部移动...")
        # 调用父类 QListWidget 的 dropEvent 方法来处理列表项的重新排序
        super().dropEvent(event)
        event.acceptProposedAction() # 接受内部移动放置操作
        self.logger.info("dropEvent: 内部移动事件已由基类处理并接受。")
# --- 结束自定义 QListWidget ---


# --- GUI 信号管理类 ---
class GuiSignals(QObject):
    """
    一个简单的 QObject 子类，用于定义 GUI 线程可以接收的信号。
    主要目的是允许非 Qt 对象（例如运行在其他线程中的代码）通过这些信号
    安全地将信息（日志、错误）发送回 GUI 线程进行处理。
    """
    # 定义日志信号，参数：消息字符串 (str), 消息类型字符串 (str)
    log_signal = pyqtSignal(str, str)
    # 定义错误信号，参数：错误消息字符串 (str)
    error_signal = pyqtSignal(str)
# --- 结束 GUI 信号管理类 ---


# --- 翻译工作线程控制器 ---
class TranslationWorker(QObject):
    """
    负责在后台线程执行批量翻译任务的控制器类。
    继承自 QObject 以支持信号和槽机制。
    这个类的实例会被移动到 QThread 中运行。

    信号:
        finished (pyqtSignal(bool, bool)): 任务完成时发射。参数：
                                            - overall_success (bool): True 表示所有文件处理成功或被跳过，False 表示有严重错误或任务被取消。
                                            - was_cancelled (bool): True 表示任务是因用户取消而结束的。
        progress (pyqtSignal(int)): 整体任务进度更新时发射。参数：0 到 100 的整数百分比。
        chunk_progress (pyqtSignal(int)): 当前正在处理文件的内部块进度更新时发射。参数：0 到 100 的整数百分比。
        log (pyqtSignal(str, str)): 需要在 GUI 日志区域显示消息时发射。参数：消息字符串, 消息类型。
        error (pyqtSignal(str)): 发生需要弹出错误对话框的错误时发射。参数：错误消息字符串。
        file_status (pyqtSignal(str)): 需要更新 GUI 底部状态栏文本时发射。参数：状态文本字符串。
        paused (pyqtSignal()): 任务被暂停时发射。
        resumed (pyqtSignal()): 任务从暂停状态恢复时发射。
        cancelled (pyqtSignal()): 任务被取消时发射。
        file_item_status_update (pyqtSignal(str, str, object)): 需要更新文件列表中某个特定项的状态时发射。参数：
                                                                - 文件路径 (str)
                                                                - 状态码 (str, 如 STATUS_PROCESSING)
                                                                - 附加数据 (object, 可选，如错误信息或进度详情)
    """
    # --- 信号定义 ---
    finished = pyqtSignal(bool, bool) # (overall_success, was_cancelled)
    progress = pyqtSignal(int)        # 总体进度
    chunk_progress = pyqtSignal(int)  # 单文件块进度
    log = pyqtSignal(str, str)        # GUI 日志 (message, type)
    error = pyqtSignal(str)           # 错误弹窗消息
    file_status = pyqtSignal(str)     # 底部状态栏文本
    paused = pyqtSignal()             # 暂停信号
    resumed = pyqtSignal()            # 恢复信号
    cancelled = pyqtSignal()          # 取消信号
    file_item_status_update = pyqtSignal(str, str, object) # 文件列表项状态更新 (file_path, status_code, data)

    def __init__(self, app, file_paths, settings):
        """
        初始化 TranslationWorker。

        参数:
            app (Application): 主应用程序 Application 类的实例引用，用于调用处理单个文件的方法。
            file_paths (list[str]): 需要处理的文件路径列表。
            settings (dict): 包含用户选择的翻译设置（如输出目录、语言、风格、模型、温度等）。
        """
        super().__init__()
        self.app = app                   # 主应用实例引用
        self.file_paths = file_paths     # 文件列表
        self.settings = settings         # 翻译设置
        self._is_paused = False          # 内部暂停状态标志
        self._is_cancelled = False       # 内部取消状态标志
        # 使用条件变量 (Condition) 来实现线程的暂停和恢复
        # Condition 内部封装了一个 Lock
        self._pause_cond = threading.Condition(threading.Lock())
        self.logger = worker_logger      # 使用独立的 Worker 日志记录器
        self.total_files = len(file_paths) # 总文件数
        self.files_processed_count = 0 # 已处理/正在处理的文件索引计数
        self.overall_success = True      # 总体任务成功标志
        self.logger.info("--- TranslationWorker 初始化 ---")
        self.logger.info(f"待处理文件数: {self.total_files}")
        # 记录部分文件列表和设置（用于调试）
        self.logger.debug(f"接收到的文件列表 (前5个): {self.file_paths[:5]}")
        self.logger.debug(f"接收到的翻译设置: {self.settings}")

    def run(self):
        """
        工作线程的主执行函数。
        遍历文件列表，处理每个文件，并更新进度和状态。
        """
        self.logger.info("--- TranslationWorker run() 方法启动 ---")
        # 发送任务开始的 GUI 日志
        self.log.emit(f"🚀 开始批量翻译任务，共 {self.total_files} 个文件待处理。", "info")
        was_cancelled = False # 标记任务是否因取消而结束

        # --- 检查和准备输出目录 ---
        output_dir = self.settings.get('-OUTPUT-', None) # 获取输出目录设置
        if output_dir:
            self.logger.info(f"检查并准备输出目录: {output_dir}")
            try:
                # 尝试创建输出目录，exist_ok=True 表示如果目录已存在则不报错
                os.makedirs(output_dir, exist_ok=True)
                self.log.emit(f"📂 输出目录已准备就绪: {output_dir}", "info")
                self.logger.info(f"输出目录检查/创建成功: {output_dir}")
            except Exception as e:
                # 如果创建目录失败，记录严重错误，发送错误信号，并提前结束任务
                worker_error_msg = f"创建输出目录失败: {e}"
                self.logger.error(f"严重错误: {worker_error_msg}", exc_info=True)
                self.log.emit(f"❌ 致命错误: {worker_error_msg} 任务无法继续。", "error")
                self.error.emit(worker_error_msg) # 触发错误弹窗
                self.overall_success = False # 标记任务失败
                self.logger.warning("由于输出目录错误，提前终止 Worker run()。")
                # 发射 finished 信号，通知主线程任务结束
                self.finished.emit(self.overall_success, was_cancelled)
                self.logger.info("--- TranslationWorker run() 方法结束 (因错误提前终止) ---")
                return # 结束 run 方法
        else:
            # 如果没有提供有效的输出目录，同样是严重错误
            worker_error_msg = "未提供有效的输出目录。"
            self.logger.error(f"严重错误: {worker_error_msg}")
            self.log.emit(f"❌ 致命错误: {worker_error_msg} 请先设置输出目录。", "error")
            self.error.emit(worker_error_msg)
            self.overall_success = False
            self.logger.warning("由于输出目录缺失，提前终止 Worker run()。")
            self.finished.emit(self.overall_success, was_cancelled)
            self.logger.info("--- TranslationWorker run() 方法结束 (因错误提前终止) ---")
            return

        # --- 文件处理循环 ---
        files_actually_processed = 0 # 记录实际成功处理（或跳过）的文件数
        files_failed_critically = 0   # 记录处理过程中遇到严重错误的文件数

        self.logger.info("开始遍历文件列表进行处理...")
        # 遍历文件路径列表
        for i, file_path in enumerate(self.file_paths):
            # --- 在每次循环开始时检查取消标志 ---
            if self._is_cancelled:
                self.logger.info("检测到取消请求，中断文件处理循环。")
                was_cancelled = True      # 标记为已取消
                self.overall_success = False # 取消也视为不完全成功
                break # 跳出 for 循环，结束任务

            # 更新已处理文件计数 (当前正在处理第 i 个文件)
            self.files_processed_count = i
            # 获取当前文件名用于日志和状态显示
            current_file_name = os.path.basename(file_path) if file_path else "未知文件"
            self.logger.info(f"--- 开始处理文件 {i + 1}/{self.total_files}: {current_file_name} ---")

            try:
                # --- 检查是否需要暂停 ---
                self.wait_if_paused() # 如果处于暂停状态，此方法会阻塞直到恢复
                 # --- 再次检查取消，因为可能在暂停期间被取消 ---
                if self._is_cancelled:
                    self.logger.info("从暂停恢复后检测到取消请求，中断循环。")
                    was_cancelled = True
                    self.overall_success = False
                    break # 跳出 for 循环

                # 处理 GUI 事件，保持界面响应
                QApplication.processEvents()

                # 更新底部状态栏，显示当前处理的文件
                self.file_status.emit(f"准备处理: {current_file_name} ({i + 1}/{self.total_files})")

                # --- 调用主应用的单个文件处理方法 ---
                self.logger.debug(f"调用 app.process_single_document 处理: {current_file_name}")
                # process_single_document 返回 True 表示成功或跳过，False 表示严重失败或中止
                # 将 worker 实例传递给它，以便内部可以检查暂停/取消状态和更新进度/状态
                file_processed_successfully = self.app.process_single_document(file_path, self.settings, self)
                self.logger.info(f"文件 {current_file_name} 处理完成，结果: {'成功/跳过' if file_processed_successfully else '失败/中止/取消'}")

                # --- 再次检查取消状态 ---
                # process_single_document 内部也可能因为取消而提前返回
                if self._is_cancelled:
                     self.logger.info(f"文件 {current_file_name} 处理后检测到取消信号，中断。")
                     was_cancelled = True
                     self.overall_success = False
                     # 如果文件本身处理成功，但之后任务被取消，将其状态更新为 CANCELLED
                     if file_processed_successfully:
                         self.file_item_status_update.emit(file_path, STATUS_CANCELLED, "任务被取消")
                     break # 跳出 for 循环

                # --- 根据处理结果更新统计 ---
                if file_processed_successfully:
                    files_actually_processed += 1 # 计入成功或跳过
                else:
                    # 如果返回 False，且不是因为取消导致的，则认为是严重错误
                    if not self._is_cancelled:
                        self.overall_success = False # 标记整体任务失败
                        files_failed_critically += 1 # 计入失败
                        self.logger.warning(f"文件 {current_file_name} 处理过程中遇到严重问题或中止。")
                    # 如果是因为取消返回 False，状态已在上面处理

                # --- 更新总体进度条 ---
                overall_progress = int(((i + 1) / self.total_files) * 100) if self.total_files > 0 else 0
                self.progress.emit(overall_progress)
                self.logger.debug(f"总体进度更新: {overall_progress}% (文件 {i + 1}/{self.total_files} 完成检查/处理)")

            # --- 循环内的异常处理 ---
            except FileNotFoundError as fnf_error:
                # 处理文件未找到的特定错误 (不应受取消影响)
                error_msg = f"文件未找到，无法处理: {current_file_name}"
                self.logger.error(f"[{current_file_name}] {error_msg}", exc_info=False)
                # 发送错误日志到 GUI
                self.log.emit(f"❌ [{current_file_name}] 错误: 文件未找到，已跳过。", "error")
                # 更新文件列表项状态
                if hasattr(self, 'file_item_status_update'):
                     self.file_item_status_update.emit(file_path, STATUS_ERROR_CRITICAL, "文件未找到")
                     self.logger.debug(f"已发射文件项状态更新信号: {file_path} -> {STATUS_ERROR_CRITICAL}")
                self.overall_success = False # 标记整体任务失败
                files_failed_critically += 1 # 计入失败
                # 即使文件失败，也要更新总体进度
                overall_progress = int(((i + 1) / self.total_files) * 100) if self.total_files > 0 else 0
                self.progress.emit(overall_progress)
                self.logger.debug(f"总体进度更新 (因文件未找到): {overall_progress}%")
                # 对于单个文件未找到，通常选择继续处理下一个文件，而不是中止整个任务
                # continue

            except Exception as worker_loop_e:
                # 捕获处理单个文件时发生的其他所有未预期异常 (通常是严重错误)
                error_msg = f"处理文件 {current_file_name} 过程中发生意外错误: {worker_loop_e}"
                self.logger.critical(f"严重错误: {error_msg}", exc_info=True) # 记录堆栈信息
                # 发送错误日志到 GUI，并触发错误弹窗
                self.log.emit(f"❌ [{current_file_name}] 发生意外严重错误: {worker_loop_e}，任务中止。", "error")
                self.error.emit(error_msg)
                # 更新文件列表项状态
                if hasattr(self, 'file_item_status_update'):
                    self.file_item_status_update.emit(file_path, STATUS_ERROR_CRITICAL, f"意外错误: {worker_loop_e}")
                    self.logger.debug(f"已发射文件项状态更新信号: {file_path} -> {STATUS_ERROR_CRITICAL}")
                self.overall_success = False # 标记整体任务失败
                files_failed_critically += 1 # 计入失败
                self.logger.warning("由于发生意外错误，中断 Worker 循环。")
                break # 中断整个任务循环

            self.logger.info(f"--- 文件 {current_file_name} 处理流程结束 ---")
            # --- 循环结束 ---

        # --- 任务结束处理 ---
        # 根据任务结束的原因（取消、成功、失败）发送最终的日志和状态信息
        if was_cancelled:
            # 如果是因取消而结束
            final_msg = f"🚫 翻译任务已被用户取消。已处理 {self.files_processed_count} 个文件。"
            self.log.emit(final_msg, "warning")
            self.logger.warning(f"任务被取消。处理文件数: {self.files_processed_count}")
            self.file_status.emit("任务已取消")
            # 将队列中剩余未处理的文件标记为“已取消”状态
            for j in range(self.files_processed_count, self.total_files):
                 if j < len(self.file_paths): # 确保索引有效
                      remaining_file_path = self.file_paths[j]
                      self.file_item_status_update.emit(remaining_file_path, STATUS_CANCELLED, "任务被取消")
        elif self.overall_success:
            # 如果任务成功完成
            if self.total_files > 0: # 确保至少有一个文件
                 final_msg = f"🎉 翻译任务成功完成！共处理 {self.total_files} 个文件。"
                 self.log.emit(final_msg, "success")
                 self.logger.info("批量处理成功完成。")
            else: # 如果文件队列 изначально 为空
                 final_msg = "ℹ️ 文件队列为空，未执行任何翻译任务。"
                 self.log.emit(final_msg, "info")
                 self.logger.info("文件队列为空，任务未执行。")
            # 更新底部状态栏
            self.file_status.emit(f"任务完成 ({self.total_files}/{self.total_files})")
        else:
            # 如果任务完成但有失败或中止
            final_msg = f"🏁 翻译任务完成，但存在问题或中止。总文件: {self.total_files}, 成功/跳过: {files_actually_processed}, 失败/中止: {files_failed_critically}。"
            self.log.emit(final_msg, "warning")
            self.logger.warning(f"处理完成，但有失败或警告。成功/跳过: {files_actually_processed}, 失败/中止: {files_failed_critically}")
            # 更新底部状态栏
            self.file_status.emit(f"任务完成但有错误 ({self.total_files}/{self.total_files})")

        # --- 发射 finished 信号 ---
        # 将最终的成功状态和取消状态传递给主线程
        self.logger.info(f"发射 finished 信号，状态: success={self.overall_success}, cancelled={was_cancelled}")
        self.finished.emit(self.overall_success, was_cancelled)
        self.logger.info("--- TranslationWorker run() 方法正常结束 ---")

    def pause(self):
        """
        请求暂停任务执行。
        设置暂停标志，发射 paused 信号，并更新日志和状态。
        """
        # 使用条件变量的锁来保护对 _is_paused 标志的访问
        with self._pause_cond:
            # 只有在未暂停状态下才执行暂停操作
            if not self._is_paused:
                 self._is_paused = True # 设置暂停标志
                 self.logger.info("用户请求暂停翻译任务。")
                 self.paused.emit() # 发射暂停信号
                 # 发送 GUI 日志
                 self.log.emit("⏸️ 任务已暂停。点击 '继续' 按钮恢复。", "info")
                 # 更新底部状态栏
                 current_file_num = self.files_processed_count + 1
                 self.file_status.emit(f"已暂停 (在文件 {current_file_num}/{self.total_files} 处理前)")
                 self.logger.info("Worker 状态已设置为暂停。")

    def resume(self):
        """
        请求恢复任务执行。
        清除暂停标志，通知等待的线程，发射 resumed 信号，并更新日志和状态。
        """
        # 使用条件变量的锁
        with self._pause_cond:
            # 只有在已暂停状态下才执行恢复操作
            if self._is_paused:
                self._is_paused = False # 清除暂停标志
                self.logger.info("用户请求恢复翻译任务。")
                # 通知正在 self._pause_cond.wait() 中等待的线程（即 run 方法中的 wait_if_paused）
                self._pause_cond.notify()
                self.resumed.emit() # 发射恢复信号
                # 发送 GUI 日志
                self.log.emit("▶️ 任务已恢复。", "info")
                # 更新底部状态栏，显示即将处理的文件
                current_file_num = self.files_processed_count + 1
                current_file_name = "N/A"
                # 获取下一个待处理文件的名称（如果存在）
                if current_file_num <= self.total_files and self.files_processed_count < len(self.file_paths):
                         current_file_name = os.path.basename(self.file_paths[self.files_processed_count])
                elif self.files_processed_count >= self.total_files: # 如果所有文件已处理完
                    current_file_name = "已完成所有文件"
                self.file_status.emit(f"继续处理: {current_file_name} ({current_file_num}/{self.total_files})")
                self.logger.info("Worker 状态已设置为恢复，已通知等待线程。")

    def wait_if_paused(self):
        """
        如果任务当前处于暂停状态，则阻塞当前线程直到任务被恢复。
        在等待期间会定期检查取消标志。
        """
        # 检查是否处于暂停状态
        if self._is_paused:
            # 获取条件变量的锁
            with self._pause_cond:
                # 循环检查暂停标志，防止伪唤醒 (spurious wakeups)
                while self._is_paused:
                    # --- 在等待时检查取消信号 ---
                    if self._is_cancelled:
                        self.logger.info("暂停等待期间检测到取消信号，退出等待。")
                        return # 直接返回，让调用者（run 方法）处理取消逻辑

                    self.logger.debug("Worker 检测到暂停状态，进入等待...")
                    # 在条件变量上等待，设置超时时间（例如 0.5 秒）
                    # 超时允许线程定期醒来检查 _is_cancelled 标志，即使没有收到 notify()
                    self._pause_cond.wait(timeout=0.5)
            # 跳出循环表示已不再暂停
            self.logger.debug("Worker 从暂停状态中恢复。")

    def cancel(self):
        """
        请求取消当前正在执行的翻译任务。
        设置取消标志，通知可能在暂停中等待的线程，并发出 cancelled 信号。
        """
        # 只有在未被取消的状态下才执行取消操作
        if not self._is_cancelled:
            self._is_cancelled = True # 设置取消标志
            self.logger.warning("接收到取消任务请求。")
            # --- 唤醒等待的线程 ---
            # 如果任务恰好在 pause 状态下等待 (wait_if_paused)，
            # 需要唤醒它，以便 run 循环能够检测到 _is_cancelled 标志并退出。
            with self._pause_cond:
                self._pause_cond.notify_all() # 唤醒所有在等待的线程
            # 发射取消信号
            self.cancelled.emit()
            # 发送 GUI 日志
            self.log.emit("🚫 任务取消请求已发送...", "warning")
            self.logger.info("Worker 状态已设置为取消，并已通知等待线程。")
    # --- 结束 TranslationWorker ---


# --- 主 GUI 窗口类 ---
class TranslationGUI(QMainWindow):
    """
    应用程序的主 GUI 窗口类。
    继承自 QMainWindow，负责创建和管理所有界面元素、处理用户交互、
    启动和控制后台翻译任务、显示进度和日志。

    属性:
        application (Application): 主 Application 类的实例引用。
        cache (TranslationCache): 缓存管理器实例引用。
        signals (GuiSignals): 用于接收来自非 Qt 对象的信号。
        worker (TranslationWorker): 当前后台工作线程控制器的实例（任务运行时）或 None。
        thread (QThread): 当前后台工作线程的实例（任务运行时）或 None。
        logger (logging.Logger): GUI 模块的日志记录器实例。
        status_styles (dict): 存储文件列表项不同状态对应的显示样式（图标、文本、颜色）。
        # ... 其他控件属性 (例如 self.start_btn, self.file_list_widget 等)
    """

    def __init__(self, application, cache_manager):
        """
        初始化 TranslationGUI 主窗口。

        参数:
            application (Application): 主 Application 类的实例。
            cache_manager (TranslationCache): 缓存管理器实例。
        """
        super().__init__()
        self.application = application  # 保存主应用引用
        self.cache = cache_manager    # 保存缓存管理器引用
        self.signals = GuiSignals()     # 创建信号管理器实例
        self.worker = None              # 初始化 worker 为 None
        self.thread = None              # 初始化 thread 为 None
        self.logger = gui_logger        # 使用 GUI 日志记录器
        self.logger.info("--- TranslationGUI 初始化开始 ---")

        # --- 初始化控件属性为 None ---
        # 这样做有助于代码补全和明确知道有哪些控件
        self.add_files_btn = None
        self.add_folder_btn = None
        self.remove_selected_btn = None
        self.clear_selected_cache_btn = None
        self.clear_queue_btn = None
        self.move_up_btn = None
        self.move_down_btn = None
        self.file_group_box = None
        self.file_list_widget = None # 将使用 DropListWidget
        self.clear_all_cache_btn = None
        self.output_input = None
        self.word_radio = None
        self.txt_radio = None
        self.lang_combo = None
        self.style_combo = None
        self.temp_input = None
        self.model_combo = None
        self.prompt_input = None
        self.prompt_browse_btn = None
        self.test_api_btn = None
        self.status_label = None
        self.detailed_status_label = None # 底部详细状态
        self.total_progress_label = None
        self.progress_bar = None      # 总体进度条
        self.chunk_progress_label = None
        self.chunk_progress_bar = None  # 当前文件块进度条
        self.start_btn = None
        self.pause_btn = None
        self.log_area = None
        self.cancel_btn = None        # 取消按钮
        # --- 结束控件属性初始化 ---

        # 初始化文件列表项的状态显示样式
        self.logger.debug("初始化文件列表项状态样式...")
        self.status_styles = self._init_status_styles()

        # 初始化 UI 布局和控件
        self.logger.info("初始化 UI 组件...")
        self.init_ui()
        self.logger.info("UI 组件初始化完成。")

        # 连接所有信号和槽
        self.logger.info("连接信号与槽...")
        self.connect_signals()
        self.logger.info("信号与槽连接完成。")

        # 设置 GUI 的颜色主题
        self.logger.info("设置 GUI 主题...")
        self.setup_theme()
        self.logger.info("GUI 主题设置完成。")

        # 根据初始状态更新按钮的可用性
        self.logger.info("更新初始按钮状态...")
        self.update_button_states()
        self.logger.info("初始按钮状态更新完成。")

        self.logger.info("--- TranslationGUI 初始化完成 ---")

    def _init_status_styles(self):
        """
        初始化一个字典，存储文件列表项不同状态码对应的显示信息。
        每个状态码映射到一个包含 'icon', 'text', 'color' 的字典。

        返回:
            dict: 状态码到显示样式信息的映射字典。
        """
        # 定义状态码到图标、显示文本和颜色的映射
        return {
            STATUS_PENDING: {"icon": "⚪", "text": "待处理", "color": COLORS.get("text", "#333333")},
            STATUS_PROCESSING: {"icon": "⏳", "text": "处理中...", "color": COLORS.get("primary", "#4A90E2")},
            STATUS_HASHING: {"icon": "🔑", "text": "校验中...", "color": COLORS.get("primary", "#4A90E2")},
            STATUS_PARSING: {"icon": "📄", "text": "解析中...", "color": COLORS.get("primary", "#4A90E2")},
            STATUS_SPLITTING: {"icon": "✂️", "text": "分块中...", "color": COLORS.get("primary", "#4A90E2")},
            STATUS_TRANSLATING: {"icon": "💬", "text": "翻译中...", "color": COLORS.get("accent", "#0050B3")},
            STATUS_CACHED: {"icon": "💾", "text": "缓存命中", "color": COLORS.get("cache", "#4A90E2")},
            STATUS_SAVING: {"icon": "💾", "text": "保存中...", "color": COLORS.get("success", "#4CAF50")},
            STATUS_COMPLETED_OK: {"icon": "✅", "text": "完成", "color": COLORS.get("success", "#4CAF50")},
            STATUS_COMPLETED_WARN: {"icon": "⚠️", "text": "完成(有警告)", "color": COLORS.get("warning", "#FFC107")},
            STATUS_SKIPPED_EMPTY: {"icon": "🚫", "text": "跳过(空文件)", "color": COLORS.get("warning", "#FFC107")},
            STATUS_SKIPPED_NO_CONTENT: {"icon": "🚫", "text": "跳过(无内容)", "color": COLORS.get("warning", "#FFC107")},
            STATUS_ERROR_HASH: {"icon": "❌", "text": "错误(校验)", "color": COLORS.get("error", "#F44336")},
            STATUS_ERROR_PARSE: {"icon": "❌", "text": "错误(解析)", "color": COLORS.get("error", "#F44336")},
            STATUS_ERROR_SPLIT: {"icon": "❌", "text": "错误(分块)", "color": COLORS.get("error", "#F44336")},
            STATUS_ERROR_SAVE: {"icon": "❌", "text": "错误(保存)", "color": COLORS.get("error", "#F44336")},
            STATUS_ERROR_TRANSLATE: {"icon": "❌", "text": "错误(翻译)", "color": COLORS.get("error", "#F44336")},
            STATUS_ERROR_CRITICAL: {"icon": "❌", "text": "严重错误", "color": COLORS.get("error", "#F44336")},
            STATUS_CANCELLED: {"icon": "🚫", "text": "已取消", "color": COLORS.get("cancel", "#FFA500")}, # 取消状态
            "DEFAULT": {"icon": "❓", "text": "未知状态", "color": COLORS.get("text", "#333333")} # 默认/未知状态
        }

    def setup_theme(self):
        """
        设置应用程序窗口的全局颜色主题。
        使用 QPalette 来定义窗口不同部分的颜色。
        """
        self.logger.debug("应用窗口调色板...")
        palette = self.palette() # 获取当前调色板
        # 设置窗口背景色
        palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["background"]))
        # 设置窗口主要文本颜色
        palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
        # 设置输入控件（如 QLineEdit, QTextEdit）的背景色
        palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
        # 设置视图控件（如 QListWidget）的交替行背景色
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["background"]))
        # 设置控件内的文本颜色
        palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
        # 应用修改后的调色板
        self.setPalette(palette)
        self.logger.debug("窗口调色板应用完成。")

    def init_ui(self):
        """
        初始化用户界面的所有控件和布局。
        """
        self.logger.info("开始构建 UI 布局和控件...")
        # --- 窗口基本设置 ---
        self.setWindowTitle('智能文档翻译系统') # 设置窗口标题
        new_min_size = (1400, 850) # 定义新的、更大的最小尺寸
        self.setMinimumSize(*new_min_size) # 设置窗口最小尺寸
        self.resize(*new_min_size)         # 设置窗口初始尺寸
        self.logger.info(f"窗口大小设置为最小 {new_min_size[0]}x{new_min_size[1]}，初始大小相同。")

        # --- 设置窗口图标 ---
        self.logger.debug("尝试设置窗口图标...")
        icon_path = ICON_DIR / 'Anon.ico' # 图标文件路径
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path))) # 设置图标
            self.logger.debug(f"窗口图标设置成功: {icon_path}")
        else:
             self.logger.warning(f"窗口图标文件未找到: {icon_path}")

        # --- 主布局 ---
        main_widget = QWidget() # 创建中心控件
        self.setCentralWidget(main_widget) # 设置为窗口的中心控件
        # 创建水平主布局
        main_layout = QHBoxLayout(main_widget)
        # 从配置获取边距和间距
        margins = LAYOUT["main_window"]["margins"]
        spacing = LAYOUT["main_window"]["spacing"]
        main_layout.setContentsMargins(*margins) # 设置布局外边距
        main_layout.setSpacing(spacing)          # 设置布局内控件间距
        self.logger.debug(f"主布局设置: 边距={margins}, 间距={spacing}")

        # ================================== 左侧面板 ==================================
        left_panel = QVBoxLayout() # 创建左侧垂直布局
        left_panel.setSpacing(15)  # 设置左侧面板内控件的垂直间距
        self.logger.debug("创建左侧面板布局。")

        # --- 文件队列组 ---
        # 创建文件队列的分组框，标题包含提示信息
        self.file_group_box = self.create_group("文件队列 (可拖拽文件/文件夹/排序)", COLORS["accent"])
        # 内部布局：文件列表和排序按钮在水平方向，下方是操作按钮
        file_list_layout = QHBoxLayout() # 水平布局放列表和排序按钮
        file_list_layout.setSpacing(5)
        # 创建自定义的 DropListWidget
        self.file_list_widget = DropListWidget()
        # 设置列表样式
        list_style = f"""
            QListWidget {{ background: {COLORS['surface']}; border: 1px solid {COLORS['accent']}; border-radius: 5px; color: {COLORS['text']}; padding: 5px; }}
            QListWidget::item {{ padding: 4px 0px; }}
            QListWidget::item:selected {{ background-color: {COLORS['primary']}33; color: {COLORS['text']}; }}
            QListWidget::indicator:checked {{ background-color: {COLORS['primary']}; }}
            QListWidget::indicator:unchecked {{ border: 1px solid {COLORS['accent']}; }}
        """
        self.file_list_widget.setStyleSheet(list_style)

        # 创建排序按钮的垂直布局
        sort_button_layout = QVBoxLayout()
        sort_button_layout.setSpacing(10)
        # 创建上移和下移按钮，初始禁用
        self.move_up_btn = self.create_button("", icon="up_arrow.svg", tooltip="上移选中项", enabled=False, object_name="MoveUpButton")
        self.move_down_btn = self.create_button("", icon="down_arrow.svg", tooltip="下移选中项", enabled=False, object_name="MoveDownButton")
        # 设置按钮固定大小
        self.move_up_btn.setFixedSize(30, 30)
        self.move_down_btn.setFixedSize(30, 30)
        # 将按钮添加到布局中，并使用伸缩项使其垂直居中
        sort_button_layout.addStretch()
        sort_button_layout.addWidget(self.move_up_btn)
        sort_button_layout.addWidget(self.move_down_btn)
        sort_button_layout.addStretch()

        # 将文件列表和排序按钮布局添加到水平布局中，列表占主要空间 (1)
        file_list_layout.addWidget(self.file_list_widget, 1)
        file_list_layout.addLayout(sort_button_layout)

        # 创建文件操作按钮
        self.add_files_btn = self.create_button("添加文件", color=COLORS["primary"], icon="add_file.svg", object_name="AddFilesButton")
        self.add_folder_btn = self.create_button("添加文件夹", color=COLORS["primary"], icon="folder.svg", object_name="AddFolderButton")
        self.remove_selected_btn = self.create_button("移除选中", color=COLORS["warning"], icon="remove.svg", object_name="RemoveSelectedButton")
        self.clear_selected_cache_btn = self.create_button("清除选中缓存", color=COLORS["clear"], icon="clear_cache.svg", tooltip="清除选中文件的翻译缓存", object_name="ClearSelectedCacheButton")
        self.clear_queue_btn = self.create_button("清空队列", color=COLORS["error"], icon="clear.svg", object_name="ClearQueueButton")

        # 将按钮分两行排列
        file_buttons_row1_layout = QHBoxLayout()
        file_buttons_row1_layout.setSpacing(15)
        file_buttons_row1_layout.addWidget(self.add_files_btn)
        file_buttons_row1_layout.addWidget(self.add_folder_btn)
        file_buttons_row2_layout = QHBoxLayout()
        file_buttons_row2_layout.setSpacing(15)
        file_buttons_row2_layout.addWidget(self.remove_selected_btn)
        file_buttons_row2_layout.addWidget(self.clear_selected_cache_btn)
        file_buttons_row2_layout.addWidget(self.clear_queue_btn)

        # 创建文件队列组的最终内部布局
        file_group_inner_layout = QVBoxLayout()
        file_group_inner_layout.addLayout(file_list_layout) # 添加列表和排序按钮
        file_group_inner_layout.addLayout(file_buttons_row1_layout) # 添加第一行按钮
        file_group_inner_layout.addLayout(file_buttons_row2_layout) # 添加第二行按钮
        # 将内部布局设置给文件队列分组框
        self.file_group_box.setLayout(file_group_inner_layout)
        self.logger.debug("文件队列组 UI 构建完成。")
        # --- 文件队列组结束 ---

        # --- 输出配置组 ---
        output_group = self.create_group("输出与翻译设置", COLORS["accent"])
        output_form = QFormLayout() # 使用表单布局，适合标签+控件的排列
        output_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight) # 标签右对齐
        output_form.setVerticalSpacing(12) # 设置行间距
        # 输出目录输入框和浏览按钮
        self.output_input = self.create_input(placeholder="选择批量输出目录...", object_name="OutputDirectoryInput")
        output_browse_btn = self.create_button("", icon="folder.svg", tooltip="选择保存目录", object_name="BrowseOutputButton")
        # 输出格式单选按钮
        format_group = QHBoxLayout() # 水平布局放单选按钮
        self.word_radio = self.create_radio("Word文档 (.docx)", checked=True, object_name="WordFormatRadio")
        self.txt_radio = self.create_radio("文本文件 (.txt)", object_name="TxtFormatRadio")
        format_group.addWidget(self.word_radio)
        format_group.addSpacing(20) # 添加间距
        format_group.addWidget(self.txt_radio)
        format_group.addStretch() # 添加伸缩项，使按钮靠左
        # 翻译参数下拉框和输入框
        self.lang_combo = self.create_combo(['中文', '英文', '日语', '韩语'], object_name="LanguageCombo")
        self.style_combo = self.create_combo(['标准', '日式轻小说', '正式', '通用'], object_name="StyleCombo")
        self.model_combo = self.create_combo(['DeepSeek-V3', 'DeepSeek-R1'], object_name="ModelCombo")
        self.temp_input = self.create_input("1.3", input_type="number", object_name="TemperatureInput") # 温度输入，类型为数字
        # 将控件添加到表单布局中
        path_hbox = QHBoxLayout() # 水平布局放输出路径输入框和按钮
        path_hbox.addWidget(self.output_input, 1) # 输入框占主要空间
        path_hbox.addWidget(output_browse_btn)
        output_form.addRow(self.create_label("输出目录:"), path_hbox)
        output_form.addRow(self.create_label("输出格式:"), format_group)
        output_form.addRow(self.create_label("目标语言:"), self.lang_combo)
        output_form.addRow(self.create_label("翻译风格:"), self.style_combo)
        output_form.addRow(self.create_label("模型选择:"), self.model_combo)
        output_form.addRow(self.create_label("温度值 (0-2):"), self.temp_input)
        # 设置分组框的布局
        output_group.setLayout(output_form)
        self.logger.debug("输出与翻译设置组 UI 构建完成。")
        # --- 输出配置组结束 ---

        # --- 提示词与API测试组 ---
        # 使用水平布局将提示词组和 API 测试组并排放置
        prompt_test_hbox = QHBoxLayout()
        prompt_test_hbox.setSpacing(15)
        # 自定义提示词组
        prompt_group = self.create_group("自定义提示词", COLORS["accent"])
        prompt_layout = QVBoxLayout() # 垂直布局
        # 提示词输入框，初始禁用
        self.prompt_input = self.create_input(placeholder="输入提示词或选择文件...", enabled=False, object_name="PromptInput")
        prompt_btn_layout = QHBoxLayout() # 水平布局放按钮和提示
        # 提示词文件浏览按钮，初始禁用
        self.prompt_browse_btn = self.create_button("选择文件", color=COLORS["primary"], icon="file.svg", enabled=False, object_name="BrowsePromptButton")
        # 提示标签
        tip_label = QLabel("* 选择'通用'风格后开放编辑")
        tip_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 10px;") # 设置小字体和颜色
        prompt_btn_layout.addWidget(self.prompt_browse_btn)
        prompt_btn_layout.addStretch() # 按钮靠左
        prompt_layout.addWidget(self.prompt_input) # 添加输入框
        prompt_layout.addLayout(prompt_btn_layout) # 添加按钮和提示布局
        prompt_layout.addWidget(tip_label)         # 添加提示标签
        prompt_group.setLayout(prompt_layout)

        # API 测试组
        test_api_group = self.create_group("API 连接测试", COLORS["accent"])
        test_api_layout = QVBoxLayout() # 垂直布局
        # API 测试按钮
        self.test_api_btn = self.create_button("测试连接", color=COLORS["info"], icon="connect.svg", tooltip="测试与 API 服务器的连接和密钥", object_name="TestApiButton")
        test_api_layout.addWidget(self.test_api_btn)
        test_api_layout.addStretch() # 按钮靠上
        test_api_group.setLayout(test_api_layout)
        test_api_group.setFixedWidth(150) # 设置固定宽度

        # 将两个组添加到水平布局中，提示词组占3份，API测试组占1份
        prompt_test_hbox.addWidget(prompt_group, 3)
        prompt_test_hbox.addWidget(test_api_group, 1)
        self.logger.debug("提示词与API测试组 UI 构建完成。")
        # --- 提示词与API测试组结束 ---

        # 将左侧的所有组和布局添加到左侧面板
        left_panel.addWidget(self.file_group_box)
        left_panel.addWidget(output_group)
        left_panel.addLayout(prompt_test_hbox)
        left_panel.addStretch() # 添加伸缩项，使内容靠上

        # ================================== 右侧面板 ==================================
        right_panel = QVBoxLayout() # 创建右侧垂直布局
        right_panel.setSpacing(15)  # 设置右侧面板内控件的垂直间距
        self.logger.debug("创建右侧面板布局。")

        # --- 进度与状态组 ---
        progress_group = self.create_group("进度与状态", COLORS["accent"])
        progress_layout = QVBoxLayout() # 垂直布局
        progress_layout.setSpacing(10) # 设置内部间距

        # 详细状态显示行
        status_hbox = QHBoxLayout()
        self.status_label = QLabel("状态:") # 固定标签
        self.status_label.setStyleSheet(f"color: {COLORS['text']}; font-weight: bold; min-width: 40px;")
        self.detailed_status_label = QLabel("空闲") # 显示详细状态的标签，初始为空闲
        self.detailed_status_label.setStyleSheet(f"color: {COLORS['text']};")
        self.detailed_status_label.setWordWrap(True) # 允许自动换行
        self.detailed_status_label.setObjectName("DetailedStatusLabel") # 设置对象名
        status_hbox.addWidget(self.status_label)
        status_hbox.addWidget(self.detailed_status_label, 1) # 详细状态标签占主要空间
        progress_layout.addLayout(status_hbox)

        # 总体进度条行
        total_progress_hbox = QHBoxLayout()
        self.total_progress_label = QLabel("总进度:") # 固定标签
        self.total_progress_label.setStyleSheet(f"color: {COLORS['text']}; font-weight: bold; min-width: 65px;")
        self.progress_bar = QProgressBar() # 创建总体进度条
        self.progress_bar.setRange(0, 100) # 设置范围 0-100
        progress_style = STYLES["QProgressBar"].format(**COLORS) # 获取进度条样式
        self.progress_bar.setStyleSheet(progress_style) # 应用样式
        self.progress_bar.setTextVisible(True) # 显示百分比文本
        self.progress_bar.setFormat("%p%")     # 设置文本格式为百分比
        self.progress_bar.setObjectName("TotalProgressBar") # 设置对象名
        total_progress_hbox.addWidget(self.total_progress_label)
        total_progress_hbox.addWidget(self.progress_bar, 1) # 进度条占主要空间
        progress_layout.addLayout(total_progress_hbox)

        # 当前文件块进度条行
        chunk_progress_hbox = QHBoxLayout()
        self.chunk_progress_label = QLabel("当前文件:") # 固定标签
        self.chunk_progress_label.setStyleSheet(f"color: {COLORS['text']}; font-weight: bold; min-width: 65px;")
        self.chunk_progress_bar = QProgressBar() # 创建块进度条
        self.chunk_progress_bar.setRange(0, 100) # 设置范围 0-100
        self.chunk_progress_bar.setValue(0)      # 初始值为 0
        self.chunk_progress_bar.setStyleSheet(progress_style) # 应用相同样式
        self.chunk_progress_bar.setTextVisible(True) # 显示百分比文本
        self.chunk_progress_bar.setFormat("%p%")     # 设置文本格式
        self.chunk_progress_bar.setObjectName("ChunkProgressBar") # 设置对象名
        chunk_progress_hbox.addWidget(self.chunk_progress_label)
        chunk_progress_hbox.addWidget(self.chunk_progress_bar, 1) # 进度条占主要空间
        progress_layout.addLayout(chunk_progress_hbox)

        # 设置分组框的布局
        progress_group.setLayout(progress_layout)
        self.logger.debug("进度与状态组 UI 构建完成。")
        # --- 进度与状态结束 ---

        # --- 控制按钮组 ---
        control_group = self.create_group("操作控制", COLORS["accent"])
        control_layout = QHBoxLayout() # 水平布局
        control_layout.setSpacing(15) # 设置按钮间距
        # 创建控制按钮
        self.start_btn = self.create_button("开始处理", color=COLORS["success"], icon="play.svg", object_name="StartButton")
        self.pause_btn = self.create_button("暂停", color=COLORS["warning"], icon="pause.svg", enabled=False, object_name="PauseButton") # 初始禁用
        self.clear_all_cache_btn = self.create_button("清除全部缓存", color=COLORS["clear"], icon="clear_all.svg", tooltip="清空所有文件的翻译缓存", object_name="ClearAllCacheButton")
        self.cancel_btn = self.create_button("取消", color=COLORS["error"], icon="cancel.svg", enabled=False, tooltip="取消当前翻译任务", object_name="CancelButton") # 取消按钮，初始禁用
        # 将按钮添加到布局
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.pause_btn)
        control_layout.addWidget(self.clear_all_cache_btn)
        control_layout.addWidget(self.cancel_btn) # 添加取消按钮
        # 设置分组框布局
        control_group.setLayout(control_layout)
        self.logger.debug("操作控制组 UI 构建完成。")
        # --- 控制按钮组结束 ---

        # --- 日志显示面板 ---
        log_group = self.create_group("实时日志", COLORS["accent"])
        log_layout = QVBoxLayout() # 垂直布局
        self.log_area = QTextEdit() # 创建文本编辑区域用于显示日志
        self.log_area.setReadOnly(True) # 设置为只读
        self.log_area.setFont(QFont("Consolas", 10)) # 设置等宽字体以便对齐
        # 设置日志区域样式
        log_style = f"background: {COLORS['surface']}; border-radius: 8px; padding: 8px; color: {COLORS['text']};"
        self.log_area.setStyleSheet(log_style)
        self.log_area.setObjectName("LogArea") # 设置对象名
        log_layout.addWidget(self.log_area) # 添加到布局
        log_group.setLayout(log_layout) # 设置分组框布局
        self.logger.debug("实时日志面板 UI 构建完成。")
        # --- 日志显示面板结束 ---

        # 将右侧的所有组添加到右侧面板布局
        right_panel.addWidget(progress_group)
        right_panel.addWidget(control_group)
        right_panel.addWidget(log_group, 1) # 日志区域占据剩余垂直空间 (1)

        # 将左右面板添加到主布局，左侧占 45%，右侧占 55%
        main_layout.addLayout(left_panel, 45)
        main_layout.addLayout(right_panel, 55)
        self.logger.info("UI 布局和控件构建完成。")

    def connect_signals(self):
        """
        连接界面控件的信号到对应的槽函数（处理方法）。
        """
        self.logger.info("开始连接信号与槽...")
        # --- 连接内部信号 ---
        # 连接 GuiSignals 的信号到 GUI 的处理方法
        self.signals.log_signal.connect(self.append_log)     # 连接日志信号到 append_log 方法
        self.signals.error_signal.connect(self.show_error)   # 连接错误信号到 show_error 方法
        self.logger.debug("内部信号 log_signal 和 error_signal 已连接。")

        # --- 连接控制按钮 ---
        self.start_btn.clicked.connect(self.start_translation) # 开始按钮点击连接到 start_translation
        self.pause_btn.clicked.connect(self.toggle_pause)      # 暂停/继续按钮点击连接到 toggle_pause
        self.clear_all_cache_btn.clicked.connect(self.clear_all_cache) # 清除全部缓存按钮点击连接到 clear_all_cache
        self.cancel_btn.clicked.connect(self.cancel_translation) # 取消按钮点击连接到 cancel_translation
        self.logger.debug("控制按钮 (Start, Pause, ClearAllCache, Cancel) clicked 信号已连接。")

        # --- 连接文件操作按钮 ---
        self.add_files_btn.clicked.connect(self.select_files)     # 添加文件按钮点击连接到 select_files
        self.add_folder_btn.clicked.connect(self.select_folder)   # 添加文件夹按钮点击连接到 select_folder
        self.remove_selected_btn.clicked.connect(self.remove_selected_files) # 移除选中按钮点击连接到 remove_selected_files
        self.clear_selected_cache_btn.clicked.connect(self.clear_selected_files_cache) # 清除选中缓存按钮点击连接到 clear_selected_files_cache
        self.clear_queue_btn.clicked.connect(self.clear_file_queue) # 清空队列按钮点击连接到 clear_file_queue
        self.logger.debug("文件操作按钮 (AddFiles, AddFolder, Remove, ClearSelectedCache, ClearQueue) clicked 信号已连接。")

        # --- 连接排序按钮 ---
        self.move_up_btn.clicked.connect(self.move_selected_items_up) # 上移按钮点击连接到 move_selected_items_up
        self.move_down_btn.clicked.connect(self.move_selected_items_down) # 下移按钮点击连接到 move_selected_items_down
        self.logger.debug("排序按钮 (MoveUp, MoveDown) clicked 信号已连接。")

        # --- 连接其他控件信号 ---
        # 翻译风格下拉框文本变化时，连接到 toggle_prompt_input 以启用/禁用自定义提示词框
        self.style_combo.currentTextChanged.connect(self.toggle_prompt_input)
        # 文件列表选择项变化时，连接到 update_button_states 以更新按钮状态
        self.file_list_widget.itemSelectionChanged.connect(self.update_button_states)
        # 文件列表模型插入/删除行时（即添加/删除文件后），连接到 update_button_states
        self.file_list_widget.model().rowsInserted.connect(self.update_button_states)
        self.file_list_widget.model().rowsRemoved.connect(self.update_button_states)
        # 自定义列表控件的 filesDropped 信号（外部文件拖入）连接到 handle_dropped_files
        self.file_list_widget.filesDropped.connect(self.handle_dropped_files)
        self.logger.debug("其他控件信号 (StyleCombo, FileList selection/model/drop) 已连接。")

        # --- 连接浏览按钮 ---
        # 查找输出目录浏览按钮并连接其 clicked 信号
        output_browse_btn = self.findChild(QPushButton, "BrowseOutputButton")
        if output_browse_btn:
            output_browse_btn.clicked.connect(self.select_output_dir)
            self.logger.debug("输出目录浏览按钮 clicked 信号已连接。")
        else: self.logger.warning("未能找到输出目录浏览按钮(BrowseOutputButton)。")
        # 连接提示词文件浏览按钮的 clicked 信号
        if self.prompt_browse_btn:
            self.prompt_browse_btn.clicked.connect(self.select_prompt_file)
            self.logger.debug("提示词浏览按钮 clicked 信号已连接。")
        # 连接 API 测试按钮的 clicked 信号
        if self.test_api_btn:
            self.test_api_btn.clicked.connect(self.test_api_connection_slot)
            self.logger.debug("API 测试按钮 clicked 信号已连接。")

        self.logger.info("信号与槽连接设置完成。")

    # --- UI 元素创建辅助方法 ---
    # 这些方法用于简化 UI 控件的创建过程，统一应用样式和设置。

    def create_group(self, title, color):
        """创建一个带标题和特定边框颜色的 QGroupBox。"""
        group = QGroupBox(title) # 创建分组框并设置标题
        # 从 STYLES 配置中获取样式，并格式化颜色
        group_style = STYLES["QGroupBox"].format(accent=color)
        group.setStyleSheet(group_style) # 应用样式
        return group

    def create_button(self, text="", color=None, icon=None, tooltip="", enabled=True, object_name=None):
        """创建一个 QPushButton，可选设置文本、颜色、图标、提示、状态和对象名。"""
        btn = QPushButton(text) # 创建按钮
        # 设置对象名，便于查找或调试
        if object_name: btn.setObjectName(object_name)
        else: btn.setObjectName(text.replace(" ", "") + "Button" if text else f"Button_{id(btn)}")
        btn.setEnabled(enabled) # 设置初始启用状态
        btn.setCursor(Qt.CursorShape.PointingHandCursor) # 设置鼠标悬停时光标为手形
        # 设置图标
        if icon:
            icon_path = ICON_DIR / icon # 构建图标完整路径
            # 检查图标是否存在
            if not icon_path.exists():
                 # 如果主图标不存在，尝试查找备用图标
                 fallback_icon_name = 'stop.svg' if 'cancel' in icon else 'placeholder.svg' # 为取消按钮设置备用图标
                 fallback_icon_path = ICON_DIR / fallback_icon_name
                 if fallback_icon_path.exists():
                     self.logger.warning(f"按钮 '{object_name or text}' 图标 {icon} 未找到, 使用备用图标 {fallback_icon_name}")
                     btn.setIcon(QIcon(str(fallback_icon_path))) # 使用备用图标
                 else: # 如果备用图标也不存在，记录错误
                     self.logger.error(f"按钮 '{object_name or text}' 图标 {icon} 和备用图标 {fallback_icon_name} 均未找到!")
            else: # 如果主图标存在，直接使用
                 btn.setIcon(QIcon(str(icon_path)))
        # 设置按钮颜色样式
        if color:
            try:
                # 从 STYLES 配置获取样式并格式化颜色
                btn.setStyleSheet(STYLES["QPushButton"].format(color=color))
            except KeyError as e: # 处理颜色键不存在的错误
                self.logger.error(f"应用按钮样式时出错: 缺少颜色键 '{e}' for button '{object_name or text}'")
        # 设置工具提示
        if tooltip: btn.setToolTip(tooltip)
        return btn

    def create_input(self, text="", placeholder="", input_type="text", enabled=True, object_name=None):
        """创建一个 QLineEdit，可选设置初始文本、占位符、类型（文本或数字）、状态和对象名。"""
        input_field = QLineEdit(text) # 创建输入框
        input_field.setPlaceholderText(placeholder) # 设置占位符
        # 设置对象名
        if object_name: input_field.setObjectName(object_name)
        else: input_field.setObjectName(f"LineEdit_{id(input_field)}")
        # 应用样式
        try:
            input_field.setStyleSheet(STYLES["QLineEdit"].format(**COLORS))
        except KeyError as e: # 处理颜色键错误
            self.logger.error(f"应用输入框样式时出错: 缺少颜色键 '{e}' for input '{input_field.objectName()}'")
        # 如果类型是数字，添加验证器（这里是 0.0 到 2.0 的浮点数，1 位小数）
        if input_type == "number":
            validator = QDoubleValidator(0.0, 2.0, 1) # 最小值, 最大值, 小数位数
            validator.setNotation(QDoubleValidator.Notation.StandardNotation) # 标准表示法
            input_field.setValidator(validator) # 设置验证器
        input_field.setEnabled(enabled) # 设置初始启用状态
        return input_field

    def create_combo(self, items, object_name=None):
        """创建一个 QComboBox，并添加指定的选项列表。"""
        combo = QComboBox() # 创建下拉框
        combo.addItems(items) # 添加选项
        # 设置对象名
        if object_name: combo.setObjectName(object_name)
        else: combo.setObjectName(f"ComboBox_{id(combo)}")
        # 应用样式
        try:
            combo.setStyleSheet(STYLES["QComboBox"].format(**COLORS))
        except KeyError as e: # 处理颜色键错误
            self.logger.error(f"应用下拉框样式时出错: 缺少颜色键 '{e}' for combo '{combo.objectName()}'")
        return combo

    def create_radio(self, text, checked=False, object_name=None):
        """创建一个 QRadioButton。"""
        radio = QRadioButton(text) # 创建单选按钮
        radio.setChecked(checked) # 设置初始选中状态
        # 设置对象名
        if object_name: radio.setObjectName(object_name)
        else: radio.setObjectName(text.replace(" ", "") + "Radio" if text else f"RadioButton_{id(radio)}")
        # 应用样式
        try:
            radio.setStyleSheet(STYLES["QRadioButton"].format(**COLORS))
        except KeyError as e: # 处理颜色键错误
            self.logger.error(f"应用单选按钮样式时出错: 缺少颜色键 '{e}' for radio '{radio.objectName()}'")
        return radio

    def create_label(self, text):
        """创建一个 QLabel，并设置基本样式。"""
        label = QLabel(text) # 创建标签
        # 设置标签样式（颜色、字体粗细、右边距）
        label_style = f"color: {COLORS['text']}; font-weight: normal; padding-right: 5px;"
        label.setStyleSheet(label_style)
        return label
    # --- 结束 UI 元素创建辅助方法 ---

    # --- 文件添加辅助方法 ---
    def _add_file_to_list(self, path, current_paths):
        """
        内部辅助方法，尝试将单个文件添加到文件列表控件中。
        会进行文件存在性、类型和重复性检查。

        参数:
            path (str): 文件的绝对路径。
            current_paths (set): 当前文件列表中所有文件的路径集合，用于快速检查重复。

        返回:
            bool: True 表示文件成功添加到列表，False 表示未添加（例如文件无效、重复或类型不支持）。
        """
        base_name = os.path.basename(path) # 获取文件名
        self.logger.debug(f"尝试添加文件到列表: {base_name} (路径: {path})")
        # 1. 检查文件是否存在
        if not os.path.exists(path):
            self.append_log(f"⚠️ 添加失败: 文件路径无效或不存在: {base_name}", "warning")
            self.logger.warning(f"尝试添加的文件不存在: {path}")
            return False
        # 2. 检查是否是文件（而不是目录）
        if not os.path.isfile(path):
            self.logger.warning(f"尝试添加的路径不是文件: {path}")
            # 通常拖放目录会在 _add_folder_contents_to_list 处理，这里主要是防御
            return False
        # 3. 检查文件是否已在列表中
        if path in current_paths:
             self.logger.debug(f"文件已在队列中，跳过: {base_name}")
             self.append_log(f"ℹ️ 文件已在队列中，跳过: {base_name}", "info")
             return False
        # 4. 检查文件扩展名是否支持 (.docx 或 .txt)
        if not path.lower().endswith(('.docx', '.txt')):
            self.append_log(f"⚠️ 添加失败: 不支持的文件类型 '{os.path.splitext(base_name)[1]}': {base_name} (仅支持 .docx 和 .txt)", "warning")
            self.logger.warning(f"尝试添加不支持的文件类型: {path}")
            return False
        # 5. 创建列表项并添加到列表控件
        item = QListWidgetItem(base_name) # 创建列表项，显示文件名
        item.setData(Qt.ItemDataRole.UserRole, path) # 将完整路径存储在 UserRole 数据中
        item.setToolTip(path) # 设置鼠标悬停提示为完整路径
        self.file_list_widget.addItem(item) # 添加到列表控件
        # 6. 设置初始状态为 PENDING
        self._set_item_status(item, STATUS_PENDING)
        self.logger.info(f"文件已成功添加到队列: {base_name}")
        return True # 添加成功

    def _add_folder_contents_to_list(self, folder_path, current_paths):
        """
        内部辅助方法，递归地将指定文件夹及其子文件夹中的所有支持文件添加到文件列表。
        (当前实现只添加指定文件夹根目录的文件，未递归)

        参数:
            folder_path (str): 要扫描的文件夹路径。
            current_paths (set): 当前文件列表中所有文件的路径集合，用于检查重复。

        返回:
            tuple[int, int, int]: 一个包含三个整数的元组：
                - added_count: 成功添加到列表的文件数量。
                - skipped_count: 因重复或其他原因跳过的文件/项数量。
                - unsupported_count: 因文件类型不支持而跳过的文件数量。
        """
        folder_name = os.path.basename(folder_path) # 获取文件夹名称
        self.logger.info(f"开始处理文件夹: {folder_name} (路径: {folder_path})")
        added_count = 0       # 添加计数
        skipped_count = 0     # 跳过计数（重复或其他非文件项）
        unsupported_count = 0 # 不支持类型计数
        try:
            # 检查路径是否是有效目录
            if not os.path.isdir(folder_path):
                 msg = f"提供的路径不是有效文件夹: {folder_name}"
                 self.append_log(f"⚠️ {msg}", "warning")
                 self.logger.warning(msg)
                 return 0, 0, 0 # 返回零计数
            self.logger.debug(f"遍历文件夹 '{folder_name}' 中的内容...")
            # 遍历文件夹中的所有条目
            for filename in os.listdir(folder_path):
                full_path = os.path.join(folder_path, filename) # 构建完整路径
                # 如果是文件
                if os.path.isfile(full_path):
                    # 检查是否是支持的文件类型
                    if full_path.lower().endswith(('.docx', '.txt')):
                        # 尝试添加到列表，并根据结果更新计数
                        if self._add_file_to_list(full_path, current_paths):
                            added_count += 1
                            current_paths.add(full_path) # 更新集合以防重复添加
                        else:
                            skipped_count +=1 # 文件已存在或添加失败（理论上add_file失败会返回False）
                    # 如果文件类型不支持
                    else:
                        unsupported_count += 1
                        self.logger.debug(f"跳过不支持的文件类型: {filename}")
                # 如果不是文件（例如是子目录或其他类型）
                else:
                     self.logger.debug(f"跳过非文件项目: {filename}")
                     skipped_count += 1
        # 处理访问文件夹时可能发生的 OS 错误（如权限问题）
        except OSError as e:
            msg = f"无法访问文件夹 '{folder_name}': {e}"
            self.append_log(f"❌ 错误: {msg}", "error")
            self.logger.error(f"{msg} (路径: {folder_path})", exc_info=True)
            return 0, 0, 0 # 返回零计数
        # 记录文件夹处理总结
        self.logger.info(f"文件夹 '{folder_name}' 处理完成。添加文件: {added_count}, 跳过/重复: {skipped_count}, 不支持类型: {unsupported_count}")
        # 返回计数结果
        return added_count, skipped_count, unsupported_count
    # --- 结束文件添加辅助方法 ---

    # --- 文件队列管理方法 (槽函数) ---
    def select_files(self):
        """槽函数：响应“添加文件”按钮点击，打开文件选择对话框并添加选中的文件。"""
        self.append_log("🖱️ 用户点击 '添加文件'...", "info")
        self.logger.info("用户触发 '添加文件' 操作，打开文件选择对话框...")
        # 打开文件选择对话框，允许选择多个文件，过滤器限制为 .docx 和 .txt
        paths, _ = QFileDialog.getOpenFileNames(self, "选择一个或多个文件", "", "支持格式 (*.docx *.txt)")
        # 如果用户选择了文件 (paths 列表非空)
        if paths:
            self.logger.info(f"用户选择了 {len(paths)} 个文件。开始添加到队列...")
            added_count = 0 # 记录成功添加的数量
            # 获取当前列表中的所有文件路径，用于去重
            current_paths = {self.file_list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.file_list_widget.count())}
            # 遍历选中的文件路径
            for path in paths:
                # 尝试将每个文件添加到列表
                if self._add_file_to_list(path, current_paths):
                    added_count += 1
            # 根据添加结果显示日志
            if added_count > 0 :
                self.append_log(f"➕ 通过对话框成功添加了 {added_count} 个文件到队列。", "success")
            else:
                self.append_log(f"ℹ️ 未添加新文件（可能已存在或类型不支持）。", "info")
            self.logger.info(f"文件选择操作完成，共添加 {added_count} 个新文件。")
            # 更新按钮状态（例如“清空队列”按钮可能需要启用）
            self.update_button_states()
        # 如果用户取消了选择
        else:
            self.append_log("ℹ️ 用户取消了文件选择。", "info")
            self.logger.info("用户取消了文件选择或未选择任何文件。")

    def select_folder(self):
        """槽函数：响应“添加文件夹”按钮点击，打开文件夹选择对话框并添加其中的文件。"""
        self.append_log("🖱️ 用户点击 '添加文件夹'...", "info")
        self.logger.info("用户触发 '添加文件夹' 操作，打开文件夹选择对话框...")
        # 打开文件夹选择对话框
        path = QFileDialog.getExistingDirectory(self, "选择包含文件的文件夹")
        # 如果用户选择了文件夹 (path 非空)
        if path:
            folder_name = os.path.basename(path) # 获取文件夹名称
            self.logger.info(f"用户选择了文件夹: {folder_name} (路径: {path})。开始添加内容...")
            # 获取当前列表路径用于去重
            current_paths = {self.file_list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.file_list_widget.count())}
            self.append_log(f"📂 正在扫描文件夹 '{folder_name}'...", "info")
            # 调用辅助方法处理文件夹内容
            added_count, skipped, unsupported = self._add_folder_contents_to_list(path, current_paths)
            # 根据结果显示日志
            if added_count > 0:
                self.append_log(f"➕ 从文件夹 '{folder_name}' 成功添加了 {added_count} 个文件。", "success")
            if unsupported > 0:
                self.append_log(f"ℹ️ 在文件夹 '{folder_name}' 中跳过了 {unsupported} 个不支持类型的文件。", "info")
            # 如果没有添加任何文件，也没有不支持的文件（可能是空文件夹或只有重复文件）
            if added_count == 0 and unsupported == 0:
                self.append_log(f"ℹ️ 文件夹 '{folder_name}' 中未找到新的支持文件或无法访问。", "warning")

            self.logger.info(f"文件夹选择操作完成，添加: {added_count}, 跳过/重复: {skipped}, 不支持: {unsupported}")
            # 更新按钮状态
            self.update_button_states()
        # 如果用户取消了选择
        else:
            self.append_log("ℹ️ 用户取消了文件夹选择。", "info")
            self.logger.info("用户取消了文件夹选择。")

    def handle_dropped_files(self, paths):
        """槽函数：响应 DropListWidget 的 filesDropped 信号，处理拖放的文件和文件夹。"""
        self.append_log("🖱️ 用户拖拽文件/文件夹到列表...", "info")
        self.logger.info(f"处理拖放操作，接收到 {len(paths)} 个路径...")
        added_files = 0       # 记录直接添加的文件数
        added_folders = 0     # 记录处理的文件夹数（包含有效文件）
        processed_paths = 0   # 记录处理的总路径数
        total_added_count = 0 # 记录最终添加到列表的总文件数
        total_unsupported = 0 # 记录所有不支持的文件总数
        # 获取当前列表路径用于去重
        current_paths = {self.file_list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.file_list_widget.count())}

        # 遍历拖放的所有路径
        for path in paths:
            processed_paths += 1
            # 如果是文件
            if os.path.isfile(path):
                self.logger.debug(f"拖放项是文件: {os.path.basename(path)}")
                # 尝试添加到列表
                if self._add_file_to_list(path, current_paths):
                    added_files += 1
                    total_added_count += 1
                    current_paths.add(path) # 更新集合
            # 如果是目录
            elif os.path.isdir(path):
                folder_name = os.path.basename(path)
                self.logger.debug(f"拖放项是文件夹: {folder_name}")
                self.append_log(f"📂 正在扫描拖入的文件夹 '{folder_name}'...", "info")
                # 处理文件夹内容
                count_in_folder, _, unsupported_in_folder = self._add_folder_contents_to_list(path, current_paths)
                # 如果文件夹中添加了文件
                if count_in_folder > 0:
                    added_folders += 1
                    total_added_count += count_in_folder
                # 累加不支持的文件数
                if unsupported_in_folder > 0:
                    total_unsupported += unsupported_in_folder
            # 如果既不是文件也不是目录
            else:
                self.logger.warning(f"拖放的路径既不是文件也不是文件夹: {path}")
                self.append_log(f"⚠️ 跳过无效的拖放项: {os.path.basename(path)}", "warning")

        # --- 根据结果显示总结日志 ---
        if total_added_count > 0:
            msg_parts = [] # 构建消息内容
            if added_files > 0: msg_parts.append(f"{added_files} 个文件")
            if added_folders > 0: msg_parts.append(f"来自 {added_folders} 个文件夹的内容")
            gui_msg = (f"➕ 通过拖拽成功添加了 {total_added_count} 个文件 ({', '.join(msg_parts)}).", "success")
            self.append_log(gui_msg[0], gui_msg[1])
        if total_unsupported > 0:
             self.append_log(f"ℹ️ 拖拽过程中跳过了 {total_unsupported} 个不支持类型的文件。", "info")
        # 如果没有任何文件被添加（可能是重复或类型错误）
        if total_added_count == 0 and total_unsupported == 0:
            gui_msg = "ℹ️ 拖拽的项目中没有找到新的有效文件或目录。"
            self.append_log(gui_msg, "warning")

        self.logger.info(f"拖放操作处理完成。总添加: {total_added_count}, 总跳过不支持: {total_unsupported} (共处理 {processed_paths} 个拖放路径)")
        # 如果添加了文件，更新按钮状态
        if total_added_count > 0: self.update_button_states()


    def remove_selected_files(self):
        """槽函数：响应“移除选中”按钮点击，从文件列表中移除选中的项。"""
        self.append_log("🖱️ 用户点击 '移除选中'...", "info")
        self.logger.info("用户触发 '移除选中' 操作...")
        # 获取当前选中的所有列表项
        selected_items = self.file_list_widget.selectedItems()
        # 如果没有选中项，提示用户并返回
        if not selected_items:
            self.append_log("ℹ️ 请先在列表中选择要移除的文件。", "info")
            self.logger.info("没有选中任何文件，操作取消。")
            return
        # 获取选中项的数量
        count = len(selected_items)
        self.logger.info(f"准备移除 {count} 个选中的文件...")
        # 记录部分待移除的文件名（用于调试）
        removed_names = [os.path.basename(item.data(Qt.ItemDataRole.UserRole)) for item in selected_items[:5]]
        if count > 5: removed_names.append("...")
        self.logger.debug(f"待移除文件预览: {removed_names}")

        # 获取选中项的行号，并降序排列
        # 从后往前删除可以避免因删除导致的前面项行号变化问题
        rows = sorted([self.file_list_widget.row(item) for item in selected_items], reverse=True)
        # 遍历行号并移除对应的项
        for row in rows:
            # takeItem 会从列表中移除项并返回它，我们需要手动删除它以释放内存（如果需要）
            item = self.file_list_widget.takeItem(row)
            del item # 删除 QListWidgetItem 对象
        # 记录操作结果
        gui_msg = f"➖ 已从队列移除 {count} 个文件。"
        self.append_log(gui_msg, "success")
        self.logger.info(gui_msg)
        # 更新按钮状态
        self.update_button_states()

    def clear_file_queue(self):
        """槽函数：响应“清空队列”按钮点击，清空文件列表中的所有项。"""
        self.append_log("🖱️ 用户点击 '清空队列'...", "info")
        self.logger.info("用户触发 '清空队列' 操作...")
        # 获取当前列表中的项数
        count = self.file_list_widget.count()
        # 只有在列表非空时才执行操作
        if count > 0:
            self.logger.debug("队列非空，弹出确认对话框...")
            # 弹出确认对话框
            confirm = QMessageBox.question(self, "确认操作", f"确定要清空文件队列中的全部 {count} 个文件吗？",
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, # 按钮选项
                                           QMessageBox.StandardButton.No) # 默认按钮
            # 如果用户点击了“是”
            if confirm == QMessageBox.StandardButton.Yes:
                self.logger.info("用户确认清空队列，执行清空操作...")
                # 清空列表控件
                self.file_list_widget.clear()
                # 记录操作结果
                gui_msg = "🗑️ 文件队列已清空。"
                self.append_log(gui_msg, "success")
                self.logger.info(gui_msg)
                # 更新按钮状态
                self.update_button_states()
            # 如果用户点击了“否”
            else:
                self.append_log("ℹ️ 用户取消了清空队列操作。", "info")
                self.logger.info("用户取消了清空队列操作。")
        # 如果列表本就为空
        else:
            self.append_log("ℹ️ 文件队列已为空，无需清空。", "info")
            self.logger.info("文件队列已为空，无需清空。")

    def move_selected_items_up(self):
        """槽函数：响应“上移”按钮点击，将选中的列表项向上移动。"""
        self.logger.debug("用户触发 '上移选中项' 操作...")
        # 获取选中的项
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items: # 如果没有选中项，忽略
            self.logger.debug("无选中项，操作忽略。")
            return
        moved_count = 0 # 记录实际移动的项数
        # 获取选中项的行号并升序排列
        selected_rows = sorted([self.file_list_widget.row(item) for item in selected_items])
        self.logger.debug(f"准备上移行: {selected_rows}")
        # 遍历选中的行号
        for current_row in selected_rows:
            # 只有非第一行才能上移
            if current_row > 0:
                # 检查它上面的项是否也被选中了，如果也被选中了，则不能移动（防止破坏多选块的相对顺序）
                is_prev_selected = self.file_list_widget.item(current_row - 1).isSelected()
                if not is_prev_selected:
                    # 从当前位置移除项
                    item_to_move = self.file_list_widget.takeItem(current_row)
                    # 插入到上一行
                    self.file_list_widget.insertItem(current_row - 1, item_to_move)
                    # 保持移动后的项为选中状态
                    item_to_move.setSelected(True)
                    moved_count += 1
                    self.logger.debug(f"  - 行 {current_row} ('{os.path.basename(item_to_move.data(Qt.ItemDataRole.UserRole))}') 已上移到 {current_row - 1}")
            else: # 如果是第一行
                self.logger.debug(f"  - 行 {current_row} 已经是第一行，无法上移。")
        # 如果有项被移动，更新按钮状态
        if moved_count > 0:
            self.logger.info(f"上移操作完成，共移动 {moved_count} 个项。")
            self.update_button_states()
        else:
            self.logger.debug("没有项被实际移动。")

    def move_selected_items_down(self):
        """槽函数：响应“下移”按钮点击，将选中的列表项向下移动。"""
        self.logger.debug("用户触发 '下移选中项' 操作...")
        # 获取选中的项
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items: # 如果没有选中项，忽略
            self.logger.debug("无选中项，操作忽略。")
            return
        moved_count = 0 # 记录实际移动的项数
        # 获取选中项的行号并降序排列（从下往上处理，避免索引问题）
        selected_rows = sorted([self.file_list_widget.row(item) for item in selected_items], reverse=True)
        self.logger.debug(f"准备下移行: {selected_rows}")
        max_row = self.file_list_widget.count() - 1 # 获取最后一行的索引
        # 遍历选中的行号
        for current_row in selected_rows:
            # 只有非最后一行才能下移
            if current_row < max_row:
                # 检查它下面的项是否也被选中了
                is_next_selected = self.file_list_widget.item(current_row + 1).isSelected()
                if not is_next_selected:
                    # 从当前位置移除项
                    item_to_move = self.file_list_widget.takeItem(current_row)
                    # 插入到下一行
                    self.file_list_widget.insertItem(current_row + 1, item_to_move)
                    # 保持选中状态
                    item_to_move.setSelected(True)
                    moved_count += 1
                    self.logger.debug(f"  - 行 {current_row} ('{os.path.basename(item_to_move.data(Qt.ItemDataRole.UserRole))}') 已下移到 {current_row + 1}")
            else: # 如果是最后一行
                self.logger.debug(f"  - 行 {current_row} 已经是最后一行，无法下移。")
        # 如果有项被移动，更新按钮状态
        if moved_count > 0:
            self.logger.info(f"下移操作完成，共移动 {moved_count} 个项。")
            self.update_button_states()
        else:
            self.logger.debug("没有项被实际移动。")
    # --- 结束文件队列管理方法 ---

    # --- 其他控件相关的槽函数 ---
    def select_output_dir(self):
        """槽函数：响应输出目录浏览按钮点击，打开文件夹选择对话框并更新输入框。"""
        self.append_log("🖱️ 用户点击 '选择输出目录' 按钮...", "info")
        self.logger.info("用户触发 '选择输出目录' 操作...")
        # 获取当前输入框中的路径作为默认路径
        current_dir = self.output_input.text() if self.output_input.text() else ""
        # 打开文件夹选择对话框
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", current_dir)
        # 如果用户选择了路径
        if path:
            # 更新输入框内容
            self.output_input.setText(path)
            self.append_log(f"📂 输出目录已选择: {path}", "info")
            self.logger.info(f"用户选择了输出目录: {path}")
        # 如果用户取消选择
        else:
            self.append_log("ℹ️ 用户取消了输出目录选择。", "info")
            self.logger.info("用户取消了输出目录选择。")

    def select_prompt_file(self):
        """槽函数：响应提示词文件浏览按钮点击，读取文本文件内容并更新提示词输入框。"""
        self.append_log("🖱️ 用户点击 '选择提示词文件' 按钮...", "info")
        self.logger.info("用户触发 '选择提示词文件' 操作...")
        # 打开文件选择对话框，过滤器限制为 .txt 文件
        path, _ = QFileDialog.getOpenFileName(self, "选择提示词文件", "", "文本文件 (*.txt)")
        # 如果用户选择了文件
        if path:
            base_name = os.path.basename(path) # 获取文件名
            self.logger.info(f"用户选择了提示词文件: {base_name} (路径: {path})")
            try:
                # 尝试以 UTF-8 编码读取文件内容
                self.logger.debug(f"尝试以 UTF-8 读取提示词文件: {path}")
                with open(path, "r", encoding="utf-8") as f:
                    prompt_content = f.read()
                # 更新提示词输入框
                self.prompt_input.setText(prompt_content)
                self.append_log(f"📝 已加载提示词文件: {base_name}", "success")
                self.logger.info(f"提示词文件加载成功并设置到输入框。")
            # 处理读取文件时可能发生的错误
            except Exception as e:
                error_msg = f"读取提示词文件失败: {str(e)}"
                self.show_error(error_msg) # 显示错误弹窗
                self.logger.error(f"{error_msg} (文件: {path})", exc_info=True) # 记录错误日志
        # 如果用户取消选择
        else:
            self.append_log("ℹ️ 用户取消了提示词文件选择。", "info")
            self.logger.info("用户取消了提示词文件选择。")

    def toggle_prompt_input(self, style):
        """槽函数：响应翻译风格下拉框变化，启用或禁用自定义提示词输入框和浏览按钮。"""
        self.logger.debug(f"翻译风格变更为: '{style}'，切换自定义提示词控件状态...")
        # 检查选择的风格是否是“通用”
        is_custom = (style == "通用")
        # 根据是否为“通用”风格，设置提示词输入框和浏览按钮的启用状态
        self.prompt_input.setEnabled(is_custom)
        self.prompt_browse_btn.setEnabled(is_custom)
        self.logger.debug(f"自定义提示词输入框和浏览按钮状态设置为 Enabled={is_custom}")
        # 如果切换到非“通用”风格，并且提示词框中有内容，则清空
        if not is_custom and self.prompt_input.text():
            self.prompt_input.clear()
            self.logger.debug("非 '通用' 风格，已清空自定义提示词输入框。")
            self.append_log("ℹ️ 切换到非'通用'风格，自定义提示词已清空。", "info")
    # --- 结束其他控件相关的槽函数 ---

    # --- 日志、进度、状态、错误处理方法 ---
    def append_log(self, message, msg_type="info"):
        """
        向 GUI 的日志区域 (QTextEdit) 追加一条带图标和颜色的日志消息。

        参数:
            message (str): 需要显示的消息文本。
            msg_type (str, optional): 消息类型 ('info', 'success', 'warning', 'error', 'cache', 'retry')。
                                      用于从 LOG_TYPES 配置中获取图标和颜色。默认为 'info'。
        """
        try:
            # 根据消息类型获取对应的图标和颜色配置，如果类型无效则使用 'info' 的配置
            cfg = LOG_TYPES.get(msg_type.lower(), LOG_TYPES["info"])
            # 格式化消息，添加图标前缀
            formatted_msg = f"{cfg['icon']} {message.strip()}"
            # 使用 HTML span 标签设置颜色和字体，追加到 QTextEdit
            # 这里使用了 'Microsoft YaHei' 字体以确保跨平台兼容性更好
            self.log_area.append(f"<span style='color:{cfg['color']}; font-family: Microsoft YaHei;'>{formatted_msg}</span>")
            # 自动滚动到底部，显示最新日志
            self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())
        except Exception as e:
            # 处理追加日志时可能发生的异常
            self.logger.error(f"向 GUI 日志区域添加日志时出错: {e}", exc_info=True)

    def update_progress(self, value):
        """更新总体进度条的值。"""
        self.progress_bar.setValue(value)

    def update_chunk_progress(self, value):
        """更新当前文件块进度条的值。"""
        self.chunk_progress_bar.setValue(value)

    def update_detailed_status_label(self, text):
        """更新底部详细状态标签的文本。"""
        self.detailed_status_label.setText(text)

    def show_error(self, message):
        """显示一个错误消息对话框。"""
        self.logger.error(f"向用户显示错误弹窗: {message}")
        QMessageBox.critical(self, "错误", message, QMessageBox.StandardButton.Ok)

    # --- 更新文件列表项状态的槽函数 ---
    def update_file_list_item_status(self, file_path, status_code, data=None):
        """
        槽函数：响应来自工作线程的 file_item_status_update 信号，更新文件列表中对应项的显示状态。

        参数:
            file_path (str): 需要更新状态的文件路径。
            status_code (str): 新的状态码 (例如 STATUS_PROCESSING)。
            data (object, optional): 附加数据，可能包含错误信息、进度详情等。默认为 None。
        """
        # 获取文件名用于日志
        base_name = os.path.basename(file_path) if file_path else "未知路径"
        self.logger.debug(f"接收到文件项状态更新信号: 文件='{base_name}', 状态={status_code}, 数据={data}")
        found = False # 标记是否找到了对应的列表项
        # 遍历文件列表控件中的所有项
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item is None: continue # 跳过无效项（理论上不应发生）
            # 获取存储在列表项中的文件路径
            item_path = item.data(Qt.ItemDataRole.UserRole)
            # 如果路径匹配
            if item_path == file_path:
                self.logger.debug(f"找到匹配的文件项 (行 {i})，准备更新状态...")
                # 调用内部方法设置项的状态
                self._set_item_status(item, status_code, data)
                found = True
                break # 找到后即可退出循环
        # 如果遍历完列表仍未找到匹配项
        if not found:
            self.logger.warning(f"未能在文件列表中找到需要更新状态的文件: {base_name} (路径: {file_path})")

    def _set_item_status(self, item: QListWidgetItem, status_code: str, data=None):
        """
        内部辅助方法，实际更新 QListWidgetItem 的文本、颜色和提示信息以反映新的状态。

        参数:
            item (QListWidgetItem): 需要更新的列表项对象。
            status_code (str): 新的状态码。
            data (object, optional): 附加数据。
        """
        try:
            # 获取文件路径和名称用于日志
            file_path = item.data(Qt.ItemDataRole.UserRole)
            base_name = os.path.basename(file_path) if file_path else "未知文件项"
            log_prefix = f"[{base_name}]"
            self.logger.debug(f"{log_prefix} 设置列表项状态为: {status_code}")
            # 从 status_styles 字典获取对应状态的样式配置，提供默认值
            style = self.status_styles.get(status_code, self.status_styles["DEFAULT"])
            status_text = style["text"] # 获取状态显示文本
            # 构建基础的工具提示信息
            tooltip_text = f"{base_name}\n状态: {status_text}"
            # --- 处理附加数据，用于显示更多信息 ---
            display_suffix = "" # 初始化显示文本的后缀（例如进度）
            if data:
                 self.logger.debug(f"{log_prefix} 状态附加数据: {data}")
                 data_str = str(data) # 将附加数据转为字符串
                 tooltip_text += f"\n详情: {data_str}" # 将详情添加到工具提示
                 # 如果是翻译中状态且数据是字典（包含进度信息）
                 if status_code == STATUS_TRANSLATING and isinstance(data, dict):
                      # 构建进度后缀，例如 " (1/5)"
                      display_suffix = f" ({data.get('current', '?')}/{data.get('total', '?')})"
                 # 如果是错误、警告或取消状态，显示部分附加信息作为后缀
                 elif status_code.startswith("ERROR") or status_code == STATUS_COMPLETED_WARN or status_code == STATUS_CANCELLED:
                      # 截断过长的错误信息
                      display_suffix = f" ({data_str[:20]}{'...' if len(data_str)>20 else ''})"
                 # 如果是缓存命中状态
                 elif status_code == STATUS_CACHED:
                      tooltip_text += "\n(使用缓存)" # 在提示中说明

            # --- 更新列表项显示 ---
            # 构建最终的显示文本：图标 + 状态文本 + 后缀 + 文件名
            display_text = f"{style['icon']} {status_text}{display_suffix}: {base_name}"
            item.setText(display_text) # 设置显示文本
            item.setForeground(QBrush(QColor(style["color"]))) # 设置前景色（文字颜色）
            item.setToolTip(tooltip_text) # 设置工具提示
            self.logger.debug(f"{log_prefix} 列表项显示已更新: Text='{display_text}', Color='{style['color']}', Tooltip='{tooltip_text}'")
        except Exception as e:
            # 处理设置状态时可能发生的错误
            self.logger.error(f"设置列表项状态时发生错误: {e}", exc_info=True)
    # --- 结束文件列表项状态更新 ---

    # --- 更新按钮状态 ---
    def update_button_states(self):
        """
        根据应用程序的当前状态（是否正在处理、文件队列内容、选中项等）
        更新界面上各个按钮的启用/禁用状态。
        """
        self.logger.debug("开始更新按钮状态...")
        # 检查后台线程是否正在运行
        is_processing = self.thread is not None and self.thread.isRunning()
        # 检查文件队列是否有内容
        queue_has_items = self.file_list_widget.count() > 0
        # 获取选中的项和数量
        selected_items = self.file_list_widget.selectedItems()
        selection_count = len(selected_items)
        # 是否可以与列表交互（当任务未运行时）
        can_interact_with_list = not is_processing
        self.logger.debug(f"当前状态: is_processing={is_processing}, queue_has_items={queue_has_items}, selection_count={selection_count}")

        # --- 设置按钮启用状态 ---
        # 开始按钮：队列有内容且未在处理时启用
        self.start_btn.setEnabled(queue_has_items and can_interact_with_list)
        # 暂停/继续按钮：仅在处理中启用
        self.pause_btn.setEnabled(is_processing)
        # 取消按钮：仅在处理中启用
        self.cancel_btn.setEnabled(is_processing)
        # 清除全部缓存按钮：未在处理时启用
        self.clear_all_cache_btn.setEnabled(can_interact_with_list)
        # 文件列表控件：未在处理时启用（允许添加、删除、排序）
        self.file_list_widget.setEnabled(can_interact_with_list)
        # 文件操作按钮：未在处理时启用
        self.add_files_btn.setEnabled(can_interact_with_list)
        self.add_folder_btn.setEnabled(can_interact_with_list)
        # 移除选中和清除选中缓存按钮：有选中项且未在处理时启用
        self.remove_selected_btn.setEnabled(selection_count > 0 and can_interact_with_list)
        self.clear_selected_cache_btn.setEnabled(selection_count > 0 and can_interact_with_list)
        # 清空队列按钮：队列有内容且未在处理时启用
        self.clear_queue_btn.setEnabled(queue_has_items and can_interact_with_list)
        # API 测试按钮：未在处理时启用
        self.test_api_btn.setEnabled(can_interact_with_list)

        # --- 设置排序按钮状态 ---
        can_move_up = False
        can_move_down = False
        # 仅当有选中项且未在处理时才判断是否可移动
        if selection_count > 0 and can_interact_with_list:
            # 获取选中行的索引并排序
            selected_rows = sorted([self.file_list_widget.row(item) for item in selected_items])
            # 如果最上面选中的行不是第一行，则可以上移
            if selected_rows[0] > 0:
                can_move_up = True
            # 如果最下面选中的行不是最后一行，则可以下移
            if selected_rows[-1] < self.file_list_widget.count() - 1:
                can_move_down = True
        self.move_up_btn.setEnabled(can_move_up)
        self.move_down_btn.setEnabled(can_move_down)

        # --- 更新暂停/继续按钮的文本和图标 ---
        # 检查是否正在处理且 worker 实例存在且处于暂停状态
        if is_processing and self.worker and self.worker._is_paused:
            # 如果是暂停状态，按钮显示“继续”和播放图标
            self.pause_btn.setText("继续")
            icon_path = ICON_DIR / "play.svg"
            current_pause_state = "继续"
        else:
            # 否则，按钮显示“暂停”和暂停图标
            self.pause_btn.setText("暂停")
            icon_path = ICON_DIR / "pause.svg"
            current_pause_state = "暂停"
        # 设置按钮图标
        if icon_path.exists():
            self.pause_btn.setIcon(QIcon(str(icon_path)))
        else:
            self.logger.warning(f"无法找到暂停/继续按钮的图标: {icon_path}")

        # --- 记录最终按钮状态日志 ---
        self.logger.debug("按钮状态更新完成。")
        self.logger.debug(f"  - Start Button Enabled: {self.start_btn.isEnabled()}")
        self.logger.debug(f"  - Pause Button Enabled: {self.pause_btn.isEnabled()} (Text: {current_pause_state})")
        self.logger.debug(f"  - Cancel Button Enabled: {self.cancel_btn.isEnabled()}")
        self.logger.debug(f"  - File List Enabled: {self.file_list_widget.isEnabled()}")
        self.logger.debug(f"  - Move Up/Down Enabled: {can_move_up}/{can_move_down}")
    # --- 结束更新按钮状态 ---

    # --- 暂停/恢复/取消 槽函数 ---
    def toggle_pause(self):
        """槽函数：响应暂停/继续按钮点击，切换任务的暂停状态。"""
        # 检查 worker 实例是否存在（即任务是否已启动）
        if self.worker:
            # 如果当前是暂停状态，则调用 resume() 恢复
            if self.worker._is_paused:
                self.append_log("🖱️ 用户点击 '继续' 按钮...", "info")
                self.logger.info("用户点击 '继续' 按钮，请求恢复任务...")
                self.worker.resume()
            # 如果当前是运行状态，则调用 pause() 暂停
            else:
                self.append_log("🖱️ 用户点击 '暂停' 按钮...", "info")
                self.logger.info("用户点击 '暂停' 按钮，请求暂停任务...")
                self.worker.pause()
            # 注意：暂停/恢复操作后，按钮状态会在 worker 发出 paused/resumed 信号时
            # 通过连接到 update_button_states 的槽自动更新。
        else:
            # 如果 worker 不存在，记录警告
            self.logger.warning("尝试切换暂停状态，但 Worker 不存在或未运行。")

    def cancel_translation(self):
        """槽函数：响应取消按钮点击，请求取消后台任务。"""
        self.append_log("🖱️ 用户点击 '取消' 按钮...", "warning")
        self.logger.info("用户触发 '取消' 操作...")
        # 检查后台线程和 worker 是否存在且正在运行
        if self.worker and self.thread and self.thread.isRunning():
            self.logger.info("任务正在运行，向 Worker 发送取消请求...")
            # 调用 worker 的 cancel 方法
            self.worker.cancel()
            # --- 重要：立即禁用取消按钮 ---
            # 防止用户重复点击，因为取消操作可能不是瞬时的
            self.cancel_btn.setEnabled(False)
            self.logger.info("取消按钮已禁用。")
            # 更新状态栏提示
            self.detailed_status_label.setText("正在取消任务...")
            # 其他 UI 状态（如开始/暂停按钮）将在任务实际结束后
            # (通过 _on_batch_finished / _on_thread_really_finished) 才完全重置。
        else:
            # 如果没有任务在运行
            msg = "没有正在运行的任务可以取消。"
            self.append_log(f"ℹ️ {msg}", "info")
            self.logger.warning(msg)
    # --- 结束暂停/恢复/取消 槽函数 ---

    # --- API 连接测试 槽函数 ---
    def test_api_connection_slot(self):
        """槽函数：响应“测试连接”按钮点击，调用翻译引擎的测试方法并显示结果。"""
        self.append_log("🖱️ 用户点击 '测试连接' 按钮...", "info")
        self.logger.info("用户触发 '测试连接' 操作...")
        # 检查主应用和翻译引擎是否已初始化
        if not self.application or not self.application.engine:
             msg = "无法测试 API：翻译引擎未初始化。"
             self.append_log(f"❌ {msg}", "error")
             self.logger.error(msg)
             return
        # 更新 GUI 状态：显示提示信息，禁用测试按钮，处理事件队列
        self.append_log("📡 正在测试 API 连接性，请稍候...", "info")
        self.test_api_btn.setEnabled(False)
        QApplication.processEvents() # 确保界面更新
        try:
            # 调用翻译引擎的测试方法
            self.logger.info("调用 engine.test_api_connection()...")
            success, message = self.application.engine.test_api_connection()
            # 在 GUI 日志区域显示结果
            self.append_log(message, "success" if success else "error")
            # 根据结果弹出消息框
            if success:
                self.logger.info(f"API 连接测试成功: {message}")
                QMessageBox.information(self, "测试成功", message)
            else:
                self.logger.error(f"API 连接测试失败: {message}")
                self.show_error(f"API 连接测试失败\n\n{message}") # 使用错误弹窗显示失败信息
        except Exception as e:
             # 处理测试过程中可能发生的未预期错误
             error_msg = f"测试 API 连接时发生内部错误: {e}"
             self.append_log(f"❌ {error_msg}", "error")
             self.logger.error(error_msg, exc_info=True)
             self.show_error(error_msg)
        finally:
            # 无论成功或失败，重新启用测试按钮
            if self.test_api_btn: self.test_api_btn.setEnabled(True)
            # 更新所有按钮状态
            self.update_button_states()
            self.logger.info("API 连接测试流程结束。")
    # --- 结束 API 连接测试 槽函数 ---

    # --- 启动翻译任务 ---
    def start_translation(self):
        """槽函数：响应“开始处理”按钮点击，进行任务启动前的检查、准备，并创建和启动后台工作线程。"""
        self.append_log("▶️ 用户点击 '开始处理' 按钮...", "success")
        self.logger.info("===== 用户触发 '开始处理' 操作 =====")
        # --- 防重入检查 ---
        # 如果后台线程已存在且在运行，提示用户并返回
        if self.thread and self.thread.isRunning():
            msg = "任务已经在运行中。"
            self.show_error(msg)
            self.logger.warning(msg)
            return

        # --- 输入验证 ---
        self.logger.info("检查文件队列和输出目录...")
        # 1. 检查文件队列是否为空
        if self.file_list_widget.count() == 0:
            msg = "文件队列为空，请先添加文件。"
            self.show_error(msg)
            self.logger.warning(msg)
            return
        self.logger.debug("文件队列非空。")
        # 2. 检查输出目录是否设置且有效
        output_dir = self.output_input.text().strip() # 获取并去除首尾空格
        if not output_dir:
            msg = "请指定一个有效的输出目录。"
            self.show_error(msg)
            self.logger.error(msg)
            return
        # 如果目录不存在，尝试创建
        if not os.path.isdir(output_dir):
             self.logger.warning(f"输出目录不存在: {output_dir}，尝试创建...")
             try:
                 os.makedirs(output_dir, exist_ok=True) # 创建目录，包括父目录
                 gui_msg = f"📂 已自动创建输出目录: {output_dir}"
                 self.append_log(gui_msg, "info")
                 self.logger.info(gui_msg)
             except Exception as e: # 处理创建失败
                 msg = f"指定的输出目录无效且无法创建: {e}"
                 self.show_error(msg)
                 self.logger.error(msg, exc_info=True)
                 return
        else: # 如果目录已存在
             self.logger.debug("输出目录有效。")

        # --- 获取文件列表和翻译设置 ---
        self.logger.info("获取当前文件队列顺序...")
        # 按照当前列表控件中的顺序获取所有文件路径
        file_paths = [self.file_list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.file_list_widget.count())]
        self.logger.info(f"获取到 {len(file_paths)} 个待处理文件路径。")
        self.logger.debug(f"待处理文件列表 (前5个): {file_paths[:5]}")

        self.logger.info("获取并验证翻译设置...")
        # 从界面控件获取用户选择的设置
        settings = {
            '-OUTPUT-': output_dir, # 输出目录
            '-WORD-': self.word_radio.isChecked(), # 是否输出 Word 格式
            '-LANG-': self.lang_combo.currentText(), # 目标语言名称
            '-STYLE-': self.style_combo.currentText(), # 翻译风格名称
            '-TEMP-': self.temp_input.text(), # 温度值（字符串）
            '-MODEL-': self.model_combo.currentText(), # 模型名称
            # 如果风格是“通用”，则获取自定义提示词，否则为空字符串
            '-CUSTOM_PROMPT-': self.prompt_input.text().strip() if self.style_combo.currentText() == "通用" else ""
        }
        self.logger.debug(f"获取到的设置: {settings}")
        # 验证温度值是否有效
        try:
            temp_str = settings['-TEMP-']
            temp = float(temp_str) # 尝试转换为浮点数
            assert 0 <= temp <= 2 # 检查是否在 0 到 2 之间
            self.logger.debug("温度值验证通过。")
        except (ValueError, AssertionError): # 处理转换失败或范围错误
            msg = f"无效的温度值 '{temp_str}'。请输入 0 到 2 之间的数字。"
            self.show_error(msg)
            self.logger.error(msg)
            return

        # --- 重置 UI 状态 ---
        self.logger.info("重置 UI 状态并准备启动工作线程...")
        self.progress_bar.setValue(0) # 重置总体进度条
        self.chunk_progress_bar.setValue(0) # 重置块进度条
        self.detailed_status_label.setText("准备开始...") # 更新状态栏
        self.log_area.clear() # 清空日志区域
        self.append_log("🔄 开始新的翻译任务，清空旧日志...", "info")
        self.logger.info("重置进度条、状态标签和日志区域。")
        # 将文件列表中的所有项状态重置为 PENDING
        self.logger.debug("重置文件列表项状态为 PENDING...")
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item: self._set_item_status(item, STATUS_PENDING)
        self.logger.debug("文件列表项状态重置完成。")

        # --- 创建并启动工作线程 ---
        self.logger.info("创建并配置 TranslationWorker 和 QThread...")
        self.thread = QThread(self) # 创建 QThread 实例
        # 创建 TranslationWorker 实例，传入主应用引用、文件列表和设置
        self.worker = TranslationWorker(self.application, file_paths, settings)
        # 将 worker 移动到新创建的线程中执行
        self.worker.moveToThread(self.thread)
        self.logger.debug("Worker 已移动到新线程。")

        # --- 连接 Worker 和 Thread 的信号到 GUI 的槽 ---
        self.logger.debug("开始连接 Worker 和 Thread 的信号...")
        # Worker 完成信号连接到 _on_batch_finished (接收两个参数)
        self.worker.finished.connect(self._on_batch_finished)
        # Worker 完成后，请求线程退出
        self.worker.finished.connect(self.thread.quit)
        # 线程实际结束后，连接到 _on_thread_really_finished 进行清理
        self.thread.finished.connect(self._on_thread_really_finished)
        # 线程结束后，安排 worker 对象的稍后删除（避免内存泄漏）
        self.thread.finished.connect(self.worker.deleteLater)
        # 连接 Worker 的各种状态更新信号到 GUI 的处理方法
        self.worker.log.connect(self.append_log)
        self.worker.progress.connect(self.update_progress)
        self.worker.chunk_progress.connect(self.update_chunk_progress)
        self.worker.error.connect(self.show_error)
        self.worker.file_status.connect(self.update_detailed_status_label)
        self.worker.paused.connect(self.update_button_states) # 暂停时更新按钮状态
        self.worker.resumed.connect(self.update_button_states) # 恢复时更新按钮状态
        self.worker.cancelled.connect(self.update_button_states) # 取消时也更新按钮状态
        self.worker.file_item_status_update.connect(self.update_file_list_item_status) # 文件项状态更新
        # 当线程启动时，自动调用 worker 的 run 方法开始执行任务
        self.thread.started.connect(self.worker.run)
        self.logger.debug("Worker 和 Thread 信号连接完成。")

        # --- 启动线程 ---
        self.thread.start() # 启动后台线程，这将触发 worker.run() 的执行
        gui_msg = f"⚙️ 工作线程已启动，开始处理 {len(file_paths)} 个文件。"
        self.append_log(gui_msg, "info")
        self.logger.info(gui_msg)
        # 更新按钮状态（例如禁用开始按钮，启用暂停/取消按钮）
        self.update_button_states()
        self.logger.info("===== '开始处理' 操作流程结束，任务已启动 =====")
    # --- 结束启动翻译任务 ---

    # --- 任务完成处理槽函数 ---
    def _on_batch_finished(self, success_status, was_cancelled):
        """
        槽函数：响应后台 Worker 的 finished 信号。
        在工作线程的任务逻辑执行完毕（或中止）时被调用。
        主要负责显示任务完成的最终状态消息给用户。

        参数:
            success_status (bool): True 表示任务整体成功（无严重错误），False 表示有失败或中止。
            was_cancelled (bool): True 表示任务是因用户取消而结束。
        """
        self.logger.info(f"接收到 Worker 的 finished 信号，状态: success={success_status}, cancelled={was_cancelled}。准备显示最终消息。")
        # 处理可能积压的 GUI 事件
        QApplication.instance().processEvents()

        # --- 根据结束状态显示不同的消息框 ---
        # 优先判断是否被取消
        if was_cancelled:
            msg = "翻译任务已被用户取消。"
            QMessageBox.warning(self, "任务取消", msg) # 显示警告框
            self.logger.warning(f"任务被用户取消，已显示提示框: {msg}")
        # 如果未取消且成功
        elif success_status:
             msg = "翻译任务已成功完成！"
             QMessageBox.information(self, "任务完成", msg) # 显示信息框
             self.logger.info(f"任务成功完成，已显示信息提示框: {msg}")
        # 如果未取消但有失败或警告
        else:
            msg = "翻译任务完成，但部分文件处理失败或包含警告。\n请检查文件列表和日志获取详细信息。"
            QMessageBox.warning(self, "任务完成", msg) # 显示警告框
            self.logger.warning(f"任务完成但有失败/警告，已显示警告提示框: {msg}")

        # --- 检查并修正文件列表项的最终状态 ---
        # 确保没有文件项停留在“处理中”等中间状态
        self._check_final_item_states(was_cancelled)
        self.logger.debug("_on_batch_finished 处理完毕。")

    def _on_thread_really_finished(self):
        """
        槽函数：响应后台 QThread 的 finished 信号。
        在线程的事件循环完全退出后被调用。
        主要负责清理工作线程相关的资源和重置 GUI 状态。
        """
        self.logger.info("接收到 QThread 的 finished 信号，工作线程事件循环已结束。")
        # 记录任务结束日志（如果不是因为取消）
        # 避免在取消时重复记录结束日志
        if not (self.worker and self.worker._is_cancelled):
            self.append_log("⏹️ 后台处理任务已完全结束。", "info")

        # --- 再次检查文件列表项状态 ---
        # 作为最后的保障，确保所有项状态正确
        self.logger.debug("执行最终的列表项状态检查...")
        # 获取可能的取消状态
        was_cancelled_check = self.worker._is_cancelled if self.worker else False
        self._check_final_item_states(was_cancelled_check)

        # --- 清理资源 ---
        self.logger.debug("清理 Worker 和 Thread 的引用...")
        self.thread = None # 清除线程引用
        self.worker = None # 清除 Worker 引用（其 deleteLater 会稍后执行）
        self.logger.info("Worker 和 Thread 引用已清理。")

        # --- 重置 UI 状态 ---
        self.logger.debug("重置 UI 控件状态为任务结束状态...")
        self.update_button_states() # 更新按钮状态（例如启用开始按钮）
        self.detailed_status_label.setText("空闲") # 将状态栏设置为空闲
        self.logger.info("UI 状态已重置为任务结束状态。")
        self.logger.info("--- 后台任务彻底结束 ---")

    def _check_final_item_states(self, was_cancelled):
        """
        内部辅助方法，在任务结束后检查文件列表，确保没有列表项停留在中间处理状态。
        如果发现有项处于中间状态，则根据任务是否被取消将其标记为“已取消”或“完成(有警告)”。

        参数:
            was_cancelled (bool): 指示任务是否因取消而结束。
        """
        self.logger.debug(f"开始最终文件列表项状态检查... (任务是否取消: {was_cancelled})")
        items_corrected = 0 # 记录被修正状态的项数
        # 理论上此时线程应该已结束，但添加检查以防万一
        is_still_processing = self.thread is not None and self.thread.isRunning()
        if is_still_processing: self.logger.warning("执行最终状态检查时，发现线程仍在运行？")

        # 遍历文件列表中的所有项
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item is None: continue
            current_text = item.text() # 获取当前显示文本
            # 获取文件名
            file_name = os.path.basename(item.data(Qt.ItemDataRole.UserRole)) if item.data(Qt.ItemDataRole.UserRole) else f"项_{i}"

            # 定义所有表示“处理中”或“待处理”的状态码
            intermediate_or_pending_codes = [
                STATUS_PROCESSING, STATUS_HASHING, STATUS_PARSING, STATUS_SPLITTING,
                STATUS_TRANSLATING, STATUS_SAVING, STATUS_PENDING
            ]
            # 获取这些状态码对应的显示文本
            intermediate_status_texts = [self.status_styles[code]["text"] for code in intermediate_or_pending_codes if code in self.status_styles]

            is_intermediate_or_pending = False # 标记当前项是否处于中间状态
            current_status_text = "未知中间/待处理状态"
            # 检查当前项的显示文本是否包含任何中间状态的文本
            for status_str in intermediate_status_texts:
                # 简单的字符串包含检查（可能需要更精确的匹配）
                if status_str in current_text:
                    is_intermediate_or_pending = True
                    current_status_text = status_str
                    break

            # 如果项处于中间或待处理状态
            if is_intermediate_or_pending:
                # 根据任务是否被取消决定最终状态
                final_state_code = STATUS_CANCELLED if was_cancelled else STATUS_COMPLETED_WARN
                # 设置附加信息
                final_state_data = "任务被取消" if was_cancelled else "状态未明确更新"
                final_state_reason = "取消" if was_cancelled else "未收到最终状态"

                # 记录警告日志
                self.logger.warning(f"任务结束后，文件 '{file_name}' 状态仍为中间/待处理 ('{current_status_text}')，可能因 ({final_state_reason}) 未完成。标记为 '{self.status_styles[final_state_code]['text']}'。")
                # 发送 GUI 日志
                self.append_log(f"⚠️ 文件 '{file_name}' 状态未明确更新或因取消未完成，标记为 '{self.status_styles[final_state_code]['text']}'。", "warning")
                # 更新列表项状态
                self._set_item_status(item, final_state_code, final_state_data)
                items_corrected += 1

        # 记录最终检查结果
        if items_corrected > 0:
            self.logger.info(f"最终状态检查完成，修正了 {items_corrected} 个停留在中间或待处理状态的列表项。")
        else:
            self.logger.debug("最终状态检查完成，未发现需要修正状态的列表项。")
    # --- 结束任务完成处理槽函数 ---

    # --- 缓存清除方法 ---
    def clear_all_cache(self):
        """槽函数：响应“清除全部缓存”按钮点击，清空所有翻译缓存。"""
        self.append_log("🖱️ 用户点击 '清除全部缓存'...", "info")
        self.logger.info("用户触发 '清除全部缓存' 操作...")
        # 检查任务是否正在运行
        if self.thread and self.thread.isRunning():
            msg = "请等待当前任务完成后再清除缓存。"
            self.show_error(msg)
            self.logger.warning(msg)
            return
        # 弹出确认对话框（这是一个危险操作）
        self.logger.debug("弹出确认对话框...")
        confirm = QMessageBox.question(self, "确认操作",
                                       "⚠️ 确定要清空 *所有* 翻译缓存吗？\n此操作不可恢复，将影响所有文件的缓存！",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        # 如果用户确认
        if confirm == QMessageBox.StandardButton.Yes:
            self.logger.info("用户确认清除全部缓存，执行操作...")
            self.append_log("🗑️ 正在清除所有翻译缓存，请稍候...", "cache")
            QApplication.processEvents() # 刷新界面显示提示信息
            try:
                # 调用缓存管理器的 clear_all_cache 方法
                self.cache.clear_all_cache() # 该方法内部有详细日志
                # 显示成功信息
                gui_msg = "✅ 已成功清空 *所有* 翻译缓存。"
                self.append_log(gui_msg, "success")
                self.logger.info(gui_msg)
                QMessageBox.information(self, "操作成功", "全部翻译缓存已成功清除。")
            except Exception as e:
                # 处理清除过程中可能发生的错误
                error_msg = f"清空全部缓存失败: {str(e)}"
                self.show_error(error_msg)
                self.logger.error(error_msg, exc_info=True)
        # 如果用户取消
        else:
            self.append_log("ℹ️ 用户取消了清除全部缓存操作。", "info")
            self.logger.info("用户取消了清除全部缓存操作。")

    def clear_selected_files_cache(self):
        """槽函数：响应“清除选中缓存”按钮点击，清除文件列表中选中项对应的缓存。"""
        self.append_log("🖱️ 用户点击 '清除选中缓存'...", "info")
        self.logger.info("用户触发 '清除选中缓存' 操作...")
        # 检查任务是否正在运行
        if self.thread and self.thread.isRunning():
            msg = "请等待当前任务完成后再清除缓存。"
            self.show_error(msg)
            self.logger.warning(msg)
            return
        # 获取选中的列表项
        selected_items = self.file_list_widget.selectedItems()
        # 如果没有选中项，提示用户
        if not selected_items:
            msg = "请先在文件队列中选择要清除缓存的文件。"
            self.show_error(msg)
            self.logger.warning(msg)
            return
        # 获取选中数量和部分文件名用于确认对话框
        count = len(selected_items)
        self.logger.info(f"准备清除 {count} 个选中文件的缓存...")
        file_names = [os.path.basename(item.data(Qt.ItemDataRole.UserRole)) for item in selected_items[:10]]
        if count > 10: file_names.append("...")
        confirm_msg = f"确定要清除以下 {count} 个选中文件的翻译缓存吗？\n\n - " + "\n - ".join(file_names) + "\n\n此操作不可恢复！"
        # 弹出确认对话框
        self.logger.debug("弹出确认对话框...")
        confirm = QMessageBox.question(self, "确认操作", confirm_msg,
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        # 如果用户确认
        if confirm == QMessageBox.StandardButton.Yes:
            self.logger.info("用户确认清除选中文件缓存，开始逐个处理...")
            self.append_log(f"🗑️ 正在清除 {count} 个选中文件的缓存...", "cache")
            QApplication.processEvents() # 刷新界面

            cleared_count = 0 # 记录成功清除的数量
            failed_files = [] # 记录清除失败的文件和原因
            # 获取一个操作日志记录器（可选，用于记录更详细的操作追踪）
            op_logger = logging.getLogger("OperationLogger") # 可以定义一个新的记录器

            # 遍历选中的项
            for item in selected_items:
                file_path = item.data(Qt.ItemDataRole.UserRole) # 获取文件路径
                file_name = os.path.basename(file_path)       # 获取文件名
                self.logger.info(f"处理文件: {file_name}")
                try:
                    # 检查文件是否存在，如果不存在则无法获取哈希
                    if not os.path.exists(file_path):
                        msg = f"文件 '{file_name}' 不存在，无法获取哈希值，跳过清除。"
                        self.append_log(f"⚠️ [{file_name}] {msg}", "warning")
                        self.logger.warning(msg)
                        failed_files.append(file_name + " (文件不存在)")
                        continue # 处理下一个文件
                    # 获取文件哈希
                    self.logger.debug(f"计算文件哈希: {file_name}")
                    file_hash = get_file_hash(file_path) # get_file_hash 内部有日志
                    log_msg = f"准备清除文件 '{file_name}' (哈希: {file_hash[:8]}...) 的缓存"
                    self.logger.info(log_msg)
                    op_logger.info(log_msg) # 记录到操作日志
                    self.append_log(f"   → 正在清除 '{file_name}' 的缓存...", "cache")
                    QApplication.processEvents() # 刷新日志
                    # 调用缓存管理器的清除方法
                    self.cache.purge_session_cache(file_hash) # purge_session_cache 内部有日志
                    cleared_count += 1
                    log_msg = f"已请求清除文件 '{file_name}' (哈希: {file_hash[:8]}...) 的缓存"
                    self.logger.info(log_msg)
                    op_logger.info(log_msg)
                    # 将列表项状态重置为 PENDING
                    self.logger.debug(f"重置文件 '{file_name}' 的列表项状态为 PENDING。")
                    self._set_item_status(item, STATUS_PENDING)
                except Exception as e:
                    # 处理清除过程中发生的错误
                    error_msg = f"清除文件 '{file_name}' 缓存时出错: {str(e)}"
                    self.append_log(f"❌ [{file_name}] 清除缓存失败: {e}", "error")
                    self.logger.error(error_msg, exc_info=True)
                    op_logger.error(error_msg, exc_info=True)
                    failed_files.append(f"{file_name} (错误: {e})")

            # --- 显示最终结果 ---
            self.logger.info("清除选中文件缓存操作处理完毕。")
            gui_msg = ""
            log_msg = ""
            summary_type = "info" # 默认消息类型
            # 构建成功消息
            if cleared_count > 0:
                gui_msg += f"✅ 已完成清除 {cleared_count} 个选中文件缓存的请求，状态已重置。"
                log_msg += f"成功请求清除 {cleared_count} 个文件的缓存。"
                summary_type = "success"
            # 构建失败消息
            if failed_files:
                fail_details = "\n - ".join(failed_files)
                # 如果有成功也有失败，类型为 warning；如果全部失败，类型为 error
                summary_type = "error" if cleared_count == 0 else "warning"
                gui_msg += f"\n❌ 但有 {len(failed_files)} 个文件清除失败:\n - {fail_details}"
                log_msg += f" 但有 {len(failed_files)} 个文件清除失败: {failed_files}"
                # 弹出错误框显示失败详情
                self.show_error("部分文件缓存清除失败:\n - " + fail_details)
            # 如果有成功且无失败，显示信息框
            elif cleared_count > 0:
                QMessageBox.information(self, "操作完成", f"已成功请求清除 {cleared_count} 个选中文件的缓存。")

            # 在 GUI 日志区域显示总结信息
            if gui_msg: self.append_log(gui_msg.strip(), summary_type)
            # 记录文件日志总结
            if log_msg: self.logger.info(log_msg.strip())
            # 如果既没有成功也没有失败（例如选中文件都不存在）
            if cleared_count == 0 and not failed_files:
                no_action_msg = "ℹ️ 没有选中文件的缓存被清除（可能文件不存在或未缓存）。"
                self.append_log(no_action_msg, "info")
                self.logger.info(no_action_msg)
        # 如果用户取消确认
        else:
            self.append_log("ℹ️ 用户取消了清除选中文件缓存操作。", "info")
            self.logger.info("用户取消了清除选中文件缓存操作。")
    # --- 结束缓存清除方法 ---

    # --- 窗口关闭事件处理 ---
    def closeEvent(self, event):
        """
        重写 QMainWindow 的 closeEvent 方法。
        在用户尝试关闭窗口时被调用。
        当前实现允许直接关闭窗口，不检查后台任务。

        参数:
            event (QCloseEvent): 关闭事件对象。
        """
        self.logger.info("捕获到窗口关闭事件 (closeEvent)...")
        # 不再检查后台任务，直接准备关闭
        self.append_log("🚪 应用程序即将关闭...", "info")
        self.logger.info("窗口关闭事件被接受。")
        # 可选：在这里添加最终的清理逻辑，例如确保缓存已保存
        # if self.cache:
        #     try:
        #         self.cache.save_cache() # 确保最后状态被保存
        #         self.logger.info("最终缓存保存尝试完成。")
        #     except Exception as e:
        #         self.logger.error(f"关闭前保存缓存失败: {e}", exc_info=True)
        event.accept() # 接受关闭事件，允许窗口关闭
    # --- 结束窗口关闭事件处理 ---

# --- 结束 TranslationGUI 类 ---