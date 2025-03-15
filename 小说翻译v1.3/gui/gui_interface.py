# gui\gui_interface.py
"""
PyQt6 GUI界面模块
功能：提供用户交互界面，管理翻译任务流程，实现以下核心功能：
- 多线程任务管理与通信
- 实时日志显示与进度监控
- 文件选择与参数配置界面
- 翻译过程控制（启动/暂停/恢复）
核心机制：
- 信号槽机制实现线程间通信
- 现代化UI设计风格
- 线程安全的事件处理
- 响应式布局与主题定制
"""

import os
import logging
import threading
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QProgressBar, QMessageBox, QTextEdit, QLabel,
    QLineEdit, QPushButton, QRadioButton, QComboBox,
    QGroupBox, QFormLayout, QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette, QDoubleValidator

from translation.translation_engine import cache
from config.settings import GUI_CONFIG  # 新增：从配置文件中导入GUI和路径配置
from gui.gui_config import (  # 修改：从样式配置模块导入配置项
    LOG_TYPES, STYLES, LAYOUT, ICON_DIR
)
# 定义UI颜色常量（从配置文件中读取）
COLORS = GUI_CONFIG["COLORS"]

class GuiSignals(QObject):
    """GUI信号管理类
    功能：定义跨线程通信信号类型，确保线程安全的事件传递
    信号列表：
    - log_signal(str, str): 日志信号（消息内容，消息类型）
    - progress_signal(int): 进度更新信号（百分比）
    - error_signal(str): 错误通知信号（错误信息）
    - pause_signal(bool): 暂停状态信号（True/False）
    """
    log_signal = pyqtSignal(str, str)  # 参数：日志内容，日志类型（info/cache/error等）
    progress_signal = pyqtSignal(int)
    error_signal = pyqtSignal(str)
    pause_signal = pyqtSignal(bool)

class TranslationWorker(QObject):
    """翻译工作线程控制器
    功能：管理翻译任务的执行流程，处理暂停/恢复逻辑
    特性：
    - 与主线程解耦的任务执行
    - 带锁的暂停状态管理
    - 实时状态信号发射
    """
    finished = pyqtSignal()          # 任务完成信号
    progress = pyqtSignal(int)       # 进度更新信号
    log = pyqtSignal(str, str)       # 日志信号：内容，类型
    error = pyqtSignal(str)          # 错误信号
    paused = pyqtSignal()            # 暂停确认信号
    resumed = pyqtSignal()           # 恢复确认信号

    def __init__(self, app, values):
        """
        :param app: 主应用实例
        :param values: 用户输入参数字典
        """
        super().__init__()
        self.app = app
        self.values = values
        self._is_paused = False       # 暂停状态标识
        self._pause_cond = threading.Condition(threading.Lock())  # 线程条件锁
        self.logger = logging.getLogger("OperationLogger")

    def run(self):
        """翻译任务主执行方法
        执行流程：
        1. 调用主应用处理逻辑
        2. 异常捕获与信号传递
        """
        try:
            self.app.process_document(self.values, self)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def pause(self):
        """暂停任务执行
        操作流程：
        1. 设置暂停标识
        2. 发射暂停信号
        3. 记录日志
        """
        with self._pause_cond:
            self._is_paused = True
            self.paused.emit()
            self.logger.info("[Worker] 用户触发暂停操作")
            self.log.emit("⏸️ 翻译线程进入暂停状态", "info")
            self.log.emit("=== 用户触发暂停操作 ===", "info")

    def resume(self):
        """恢复任务执行
        操作流程：
        1. 清除暂停标识
        2. 唤醒等待线程
        3. 发射恢复信号
        """
        with self._pause_cond:
            self._is_paused = False
            self._pause_cond.notify()
            self.resumed.emit()
            self.logger.info("[Worker] 用户触发继续操作")
            self.log.emit("▶️ 翻译线程恢复运行", "info")
            self.log.emit("=== 用户触发继续操作 ===", "info")

    def wait_if_paused(self):
        """暂停状态检查与等待
        阻塞逻辑：当暂停标识为True时，线程进入等待状态
        """
        with self._pause_cond:
            while self._is_paused:
                self.log.emit("⏸️ 检测到暂停状态，等待恢复...", "info")
                self.logger.info("[Worker] 翻译线程处于暂停等待状态")
                self._pause_cond.wait()

class TranslationGUI(QMainWindow):
    """主GUI窗口类
    功能：构建用户界面，协调各组件交互
    布局结构：
    - 左侧面板：文件输入/参数配置
    - 右侧面板：进度控制/日志显示
    """
    def __init__(self, application):
        """
        :param application: 主应用实例
        """
        super().__init__()
        self.application = application  # 主应用引用
        self.signals = GuiSignals()     # 信号实例
        self.worker = None              # 工作线程实例占位
        self.init_ui()                  # 初始化UI组件
        self.connect_signals()          # 连接信号槽
        self.setup_theme()              # 应用主题样式

    def setup_theme(self):
        """设置全局视觉主题
        配置内容：
        - 窗口背景色
        - 基础文本颜色
        - 控件背景色
        """
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["background"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
        palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
        self.setPalette(palette)

    def init_ui(self):
        """初始化用户界面组件
        布局策略：
        - 使用QHBoxLayout实现左右分栏
        - QGroupBox组织功能区域
        - QFormLayout管理表单控件
        """
        self.setWindowTitle('智能文档翻译系统')
        # 从布局配置读取窗口尺寸
        self.setMinimumSize(*LAYOUT["main_window"]["min_size"])
        # 禁用最大化按钮保持布局稳定
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

        # 设置应用图标（使用新的路径配置）
        icon_path = ICON_DIR / 'Anon.ico'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # 主窗口布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        # 应用布局边距和间距配置
        margins = LAYOUT["main_window"]["margins"]
        main_layout.setContentsMargins(*margins)
        main_layout.setSpacing(LAYOUT["main_window"]["spacing"])

        # ================= 左侧面板 =================
        left_panel = QVBoxLayout()
        left_panel.setSpacing(15)

        # 文件输入组
        file_group = self.create_group("文件输入", COLORS["accent"])
        file_layout = QHBoxLayout()
        self.source_input = self.create_input(placeholder="选择源文件...")
        browse_btn = self.create_button("选择文件", color=COLORS["primary"], icon="folder.svg")
        browse_btn.clicked.connect(self.select_file)
        file_layout.addWidget(self.source_input)
        file_layout.addWidget(browse_btn)
        file_group.setLayout(file_layout)

        # 输出配置组
        output_group = self.create_group("输出配置", COLORS["accent"])
        output_form = QFormLayout()
        output_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        output_form.setVerticalSpacing(12)

        # 输出路径组件
        self.output_input = self.create_input(placeholder="默认保存到源目录...")
        output_browse_btn = self.create_button("", icon="folder.svg", tooltip="选择保存目录")
        output_browse_btn.clicked.connect(self.select_output_dir)

        # 格式选择组件
        format_group = QHBoxLayout()
        self.word_radio = self.create_radio("Word文档", checked=True)
        self.txt_radio = self.create_radio("文本文件")
        format_group.addWidget(self.word_radio)
        format_group.addSpacing(20)
        format_group.addWidget(self.txt_radio)
        format_group.addStretch()

        # 下拉选择组件
        self.lang_combo = self.create_combo(['中文', '英文', '日语', '韩语'])
        self.style_combo = self.create_combo(['标准', '日式轻小说', '正式', '通用'])  # 新增"通用"风格
        self.model_combo = self.create_combo(['DeepSeek-V3', 'DeepSeek-R1'])
        self.temp_input = self.create_input("1.3", input_type="number")

        # 构建表单布局
        path_hbox = QHBoxLayout()
        path_hbox.addWidget(self.output_input)
        path_hbox.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        path_hbox.addWidget(output_browse_btn)
        output_form.addRow(self.create_label("保存路径:"), path_hbox)
        output_form.addRow(self.create_label("输出格式:"), format_group)
        output_form.addRow(self.create_label("目标语言:"), self.lang_combo)
        output_form.addRow(self.create_label("翻译风格:"), self.style_combo)
        output_form.addRow(self.create_label("模型选择:"), self.model_combo)
        output_form.addRow(self.create_label("温度值 (0-2):"), self.temp_input)
        output_group.setLayout(output_form)

        left_panel.addWidget(file_group)
        left_panel.addWidget(output_group)

        # ================= 新增：固定提示词模块 =================
        prompt_group = self.create_group("自定义提示词", COLORS["accent"])
        prompt_layout = QVBoxLayout()

        # 输入框（始终存在但禁用）
        self.prompt_input = self.create_input(placeholder="输入提示词或选择文件...", enabled=False)

        # 文件选择按钮（始终存在但禁用）
        prompt_btn_layout = QHBoxLayout()
        self.prompt_browse_btn = self.create_button("选择文件",
                                                    color=COLORS["primary"],
                                                    icon="file.svg",
                                                    enabled=False)
        self.prompt_browse_btn.clicked.connect(self.select_prompt_file)

        # 提示文字（始终显示）
        tip_label = QLabel("* 选择'通用'风格后开放编辑")
        tip_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 10px;")

        # 组装组件
        prompt_btn_layout.addWidget(self.prompt_browse_btn)
        prompt_btn_layout.addStretch()
        prompt_layout.addWidget(self.prompt_input)
        prompt_layout.addLayout(prompt_btn_layout)
        prompt_layout.addWidget(tip_label)
        prompt_group.setLayout(prompt_layout)

        # 将提示词模块永久添加到左侧面板
        left_panel.addWidget(prompt_group)
        left_panel.addStretch()

        # ================= 右侧面板 =================
        right_panel = QVBoxLayout()
        right_panel.setSpacing(15)

        # 进度条组件
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        # 应用进度条样式配置
        progress_style = STYLES["QProgressBar"].format(**COLORS)
        self.progress_bar.setStyleSheet(progress_style)
        self.progress_bar.setTextVisible(LAYOUT["progress_bar"]["text_visible"])

        # 控制按钮组
        control_group = self.create_group("操作控制", COLORS["accent"])
        control_layout = QVBoxLayout()
        btn_layout = QHBoxLayout()

        self.start_btn = self.create_button("开始翻译", color=COLORS["success"], icon="play.svg")
        self.pause_btn = self.create_button("暂停", color=COLORS["warning"], icon="pause.svg", enabled=False)
        self.clear_cache_btn = self.create_button("清除缓存", color=COLORS["clear"], icon="clear.svg")
        exit_btn = self.create_button("退出", color=COLORS["error"], icon="esc.svg")
        exit_btn.clicked.connect(self.close)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.clear_cache_btn)
        btn_layout.addWidget(exit_btn)
        control_layout.addWidget(self.progress_bar)
        control_layout.addLayout(btn_layout)
        control_group.setLayout(control_layout)

        # 日志显示面板
        log_group = self.create_group("实时日志", COLORS["accent"])
        log_layout = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 10))
        # 应用日志区域样式
        log_style = f"""
            background: {COLORS["surface"]};
            border-radius: 8px;
            padding: 8px;
            color: {COLORS["text"]};
        """
        self.log_area.setStyleSheet(log_style)
        log_layout.addWidget(self.log_area)
        log_group.setLayout(log_layout)

        right_panel.addWidget(control_group)
        right_panel.addWidget(log_group)

        # 组合主布局
        main_layout.addLayout(left_panel, 40)  # 左侧占比40%
        main_layout.addLayout(right_panel, 60)  # 右侧占比60%

    def connect_signals(self):
        """连接信号与槽函数
        关键连接：
        - 日志信号绑定显示方法
        - 按钮点击绑定事件处理器
        - 进度信号绑定更新方法
        """
        self.signals.log_signal.connect(self.append_log)
        self.signals.progress_signal.connect(self.update_progress)
        self.signals.error_signal.connect(self.show_error)
        self.start_btn.clicked.connect(self.start_translation)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        # 新增：绑定风格选择事件
        self.style_combo.currentTextChanged.connect(self.toggle_prompt_input)

    def create_group(self, title, color):
        """创建样式化分组框
        :param title: 分组标题文本
        :param color: 边框颜色
        :return: 配置好的QGroupBox实例
        """
        group = QGroupBox(title)
        # 使用配置的QGroupBox样式模板
        group_style = STYLES["QGroupBox"].format(accent=color)
        group.setStyleSheet(group_style)
        return group

    def create_button(self, text="", color=None, icon=None, tooltip="", enabled=True):
        """生成标准化按钮
        :param color: 按钮背景色
        :param icon: 图标文件名（位于icons目录）
        :return: 配置好的QPushButton实例
        """
        btn = QPushButton(text)
        btn.setEnabled(enabled)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)  # 手型光标
        if icon:
            btn.setIcon(QIcon(str(ICON_DIR / icon)))  # 使用新的图标路径配置
        if color:
            # 从样式模板动态生成样式表
            btn_style = STYLES["QPushButton"].format(color=color)
            btn.setStyleSheet(btn_style)
        if tooltip:
            btn.setToolTip(tooltip)
        return btn

    def create_input(self, text="", placeholder="", input_type="text", enabled=True):
        """生成标准化输入框
        :param text: 初始文本
        :param placeholder: 占位符文本
        :param input_type: 输入类型（text/number）
        :param enabled: 是否启用输入框
        :return: 配置好的QLineEdit实例
        """
        input_field = QLineEdit(text)
        input_field.setPlaceholderText(placeholder)
        # 应用配置的输入框样式
        input_style = STYLES["QLineEdit"].format(**COLORS)
        input_field.setStyleSheet(input_style)
        if input_type == "number":
            input_field.setValidator(QDoubleValidator(0.0, 2.0, 1))  # 数值范围验证
        input_field.setEnabled(enabled)  # 设置输入框的启用状态
        return input_field

    def create_combo(self, items):
        """生成标准化下拉框
        :param items: 选项列表
        :return: 配置好的QComboBox实例
        """
        combo = QComboBox()
        combo.addItems(items)
        # 应用配置的下拉框样式
        combo_style = STYLES["QComboBox"].format(**COLORS)
        combo.setStyleSheet(combo_style)
        return combo

    def create_radio(self, text, checked=False):
        """生成标准化单选按钮
        :param checked: 默认选中状态
        :return: 配置好的QRadioButton实例
        """
        radio = QRadioButton(text)
        radio.setChecked(checked)
        # 应用配置的单选按钮样式
        radio_style = STYLES["QRadioButton"].format(**COLORS)
        radio.setStyleSheet(radio_style)
        return radio

    def create_label(self, text):
        """创建现代化标签控件
        功能：生成一个带有自定义样式的文本标签

        :param text: 标签显示的文本内容
        :return: 配置好的QLabel对象
        """
        label = QLabel(text)
        label_style = f"""
            color: {COLORS['text']};
            font-weight: bold;
            min-width: 80px;
        """
        label.setStyleSheet(label_style)
        return label

    def select_file(self):
        """选择源文件
        功能：打开文件选择对话框，允许用户选择要翻译的文件
        支持格式：.docx 和 .txt
        """
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "支持格式 (*.docx *.txt)")
        if path:
            self.source_input.setText(path)

    def select_output_dir(self):
        """选择输出目录
        功能：打开目录选择对话框，允许用户选择保存翻译结果的目录
        """
        path = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if path:
            self.output_input.setText(path)

    def select_prompt_file(self):
        """选择提示词文件
        功能：打开文件选择对话框，允许用户选择提示词文件（.txt）
        """
        path, _ = QFileDialog.getOpenFileName(self, "选择提示词文件", "", "文本文件 (*.txt)")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.prompt_input.setText(f.read())
            except Exception as e:
                self.show_error(f"读取提示词文件失败: {str(e)}")

    def toggle_prompt_input(self, style):
        """切换提示词输入可见性
        功能：当用户选择'通用'风格时，显示提示词输入区域
        :param style: 当前选择的翻译风格
        """
        is_custom = (style == "通用")
        self.prompt_input.setEnabled(is_custom)
        self.prompt_browse_btn.setEnabled(is_custom)

        # 清除非通用风格时的输入
        if not is_custom:
            self.prompt_input.clear()

    def append_log(self, message, msg_type="info"):
        """增强型日志追加方法
        功能：根据日志类型（info/success/warning等）动态设置日志的颜色和图标

        :param message: 日志消息内容
        :param msg_type: 日志类型，决定颜色和图标
        """
        # 使用配置的日志类型设置
        cfg = LOG_TYPES.get(msg_type.lower(), LOG_TYPES["info"])
        formatted_msg = f"{cfg['icon']} {message.strip()}"
        self.log_area.append(
            f"<span style='color:{cfg['color']}; font-family: Microsoft YaHei;'>• {formatted_msg}</span>"
        )
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    def update_progress(self, value):
        """更新进度条
        功能：设置进度条的当前值

        :param value: 进度值（0-100）
        """
        self.progress_bar.setValue(value)

    def show_error(self, message):
        """显示错误信息
        功能：弹出一个错误提示框，显示错误消息

        :param message: 错误消息内容
        """
        QMessageBox.critical(self, "错误",
                             f"<span style='color:{COLORS['text']}'>{message}</span>",
                             QMessageBox.StandardButton.Ok)

    def toggle_pause(self):
        """切换暂停/继续状态
        功能：控制翻译任务的暂停和恢复
        """
        if self.worker:
            if self.worker._is_paused:
                # 恢复翻译任务
                self.worker.resume()
                self.pause_btn.setText("暂停")
                self.pause_btn.setIcon(QIcon(str(ICON_DIR / "pause.svg")))  # 使用新的图标路径配置
                self.signals.log_signal.emit("▶️ 翻译已恢复", "info")
            else:
                # 暂停翻译任务
                self.worker.pause()
                self.pause_btn.setText("继续")
                self.pause_btn.setIcon(QIcon(str(ICON_DIR / "play.svg")))  # 使用新的图标路径配置
                self.signals.log_signal.emit("⏸️ 翻译已暂停", "info")

    def start_translation(self):
        """触发翻译流程
        功能：启动翻译任务，初始化工作线程并连接信号槽
        """
        # 收集用户输入参数
        values = {
            '-SOURCE-': self.source_input.text(),
            '-OUTPUT-': self.output_input.text(),
            '-WORD-': self.word_radio.isChecked(),
            '-LANG-': self.lang_combo.currentText(),
            '-STYLE-': self.style_combo.currentText(),
            '-TEMP-': self.temp_input.text(),
            '-MODEL-': self.model_combo.currentText()
        }

        # 初始化工作线程
        self.thread = QThread()
        self.worker = TranslationWorker(self.application, values)

        # 将工作对象移动到线程中
        self.worker.moveToThread(self.thread)

        # 连接信号槽
        self.worker.log.connect(self.append_log)  # 日志信号
        self.thread.started.connect(self.worker.run)  # 线程启动时执行任务
        self.worker.finished.connect(self.thread.quit)  # 任务完成时退出线程
        self.worker.finished.connect(self.worker.deleteLater)  # 任务完成后清理工作对象
        self.thread.finished.connect(self.thread.deleteLater)  # 线程退出后清理线程对象
        self.worker.progress.connect(self.update_progress)  # 进度更新信号
        self.worker.error.connect(self.show_error)  # 错误信号
        self.worker.paused.connect(lambda: self.pause_btn.setEnabled(True))  # 暂停状态信号
        self.worker.resumed.connect(lambda: self.pause_btn.setEnabled(True))  # 恢复状态信号

        # 更新按钮状态
        self.start_btn.setEnabled(False)  # 禁用开始按钮
        self.pause_btn.setEnabled(True)  # 启用暂停按钮
        self.pause_btn.setText("暂停")
        self.pause_btn.setIcon(QIcon(str(ICON_DIR / "pause.svg")))  # 使用新的图标路径配置

        # 线程结束时恢复按钮状态
        self.thread.finished.connect(lambda: self.start_btn.setEnabled(True))
        self.thread.finished.connect(lambda: self.pause_btn.setEnabled(False))

        # 启动线程
        self.thread.start()

    def clear_cache(self):
        """
        清除缓存事件处理
        功能描述：
        1. 弹出确认对话框，提示用户是否确认清空所有翻译缓存
        2. 如果用户确认，调用 `cache.clear_all_cache` 方法清空所有缓存数据
        3. 成功清空缓存时，发送成功信号并记录操作日志
        4. 如果清空失败，捕获异常并显示错误提示，同时记录错误日志

        流程步骤：
        - 使用 `QMessageBox.question` 弹出确认对话框
        - 用户选择“是”或“否”来决定是否执行清空操作
        - 确认后，调用外部的缓存管理器 `cache` 的 `clear_all_cache` 方法
        - 捕获清空过程中可能出现的异常，并提供用户友好的错误提示
        - 成功或者失败后，通过信号机制通知主界面更新状态

        注意事项：
        - 清空操作是不可逆的，缓存数据将永久丢失
        - 通过日志记录功能，记录用户的操作行为和异常信息
        - 异常处理确保程序不会因错误而崩溃，同时保持足够的故障透明度
        """
        confirm = QMessageBox.question(
            self, "确认操作",
            "确定要清空所有翻译缓存吗？此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            try:
                cache.clear_all_cache()  # 调用缓存管理器的清空方法
                self.signals.log_signal.emit("🗑️ 已成功清空所有翻译缓存", "cache")
                logging.getLogger("OperationLogger").info("用户手动清空缓存")
            except Exception as e:
                self.show_error(f"清空缓存失败: {str(e)}")
                self.signals.log_signal.emit(f"❌ 缓存清除失败: {str(e)}", "error")