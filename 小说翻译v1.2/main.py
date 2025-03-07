# main.py
"""主程序入口模块"""
import sys
import logging
import os
from datetime import datetime
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

# 自定义模块导入
from gui.gui_interface import TranslationGUI
from config.config_manager import validate_config
from translation.translation_engine import TranslationEngine, cache
from file_processor.file_handler import (
    get_file_hash,
    extract_text_from_docx,
    save_as_word,
    dynamic_split, save_as_txt, extract_text_from_txt
)
from config.settings import (
    PATH_CONFIG,
    GUI_CONFIG,
    FILE_HANDLER_CONFIG
)


def setup_logging():
    """配置全局日志系统"""
    os.makedirs(PATH_CONFIG["LOG_DIR"], exist_ok=True)
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_file = datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"

    # 基础日志配置
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(os.path.join(PATH_CONFIG["LOG_DIR"], log_file), encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    # 操作日志特殊配置
    op_logger = logging.getLogger("OperationLogger")
    op_logger.setLevel(logging.INFO)

    # 翻译引擎调试日志配置
    engine_logger = logging.getLogger("TranslationEngine")
    engine_logger.setLevel(logging.DEBUG)


class Application:
    """主应用程序控制器"""

    def __init__(self):
        setup_logging()
        self.logger = logging.getLogger("Main")
        self.logger.info("[Main] 应用程序初始化开始")

        try:
            self.qt_app = QApplication(sys.argv)
            self.api_key = validate_config()
            self._init_ui()  # 先初始化UI（创建self.gui）
            self._init_core_components()  # 再初始化核心组件（传递self.gui）
            self.logger.info("[Main] 应用程序初始化完成")
        except Exception as e:
            self.logger.critical("[Main] 初始化失败", exc_info=True)
            raise

    def _init_core_components(self):
        """初始化核心组件"""
        self.engine = TranslationEngine(self.api_key)
        self.engine.gui = self.gui
        self.logger.debug("[Main] 翻译引擎初始化完成")

    def _init_ui(self):
        """初始化用户界面"""
        self.qt_app.setStyle("Fusion")
        self.qt_app.setFont(QFont(
            GUI_CONFIG["FONT"]["family"],
            GUI_CONFIG["FONT"]["size"]
        ))
        self.gui = TranslationGUI(self)
        self.gui.show()

    def _validate_input(self, values):
        """用户输入验证"""
        self.logger.debug("[Main] 验证用户输入")
        if not values['-SOURCE-']:
            raise ValueError("请选择要翻译的文件")
        if not os.path.exists(values['-SOURCE-']):
            raise FileNotFoundError("选择的文件不存在")

        try:
            temp = float(values['-TEMP-'])
            if not 0 <= temp <= 2:
                raise ValueError("温度值超出范围(0-2)")
        except ValueError:
            self.logger.error("无效的温度值输入")
            raise

    def process_document(self, values, worker):
        """文档处理主流程"""
        try:
            self._validate_input(values)
            source_file = values['-SOURCE-']
            file_hash = get_file_hash(source_file)

            # 文件解析
            self._process_file(source_file, worker)

            # 翻译配置
            target_lang = self.engine.language_map[values['-LANG-']]
            style = self.engine.style_map[values['-STYLE-']]

            # 执行翻译
            translated_chunks = self._execute_translation(
                source_file, target_lang, style, values, file_hash, worker
            )

            # 保存结果
            output_path = self._generate_output_path(values)
            self._save_result(values, translated_chunks, output_path)

            # 最终状态
            cache.save_cache(force=True)
            self._update_ui_success(output_path)

        except Exception as e:
            self._handle_process_error(e)

    def _process_file(self, file_path, worker):
        """文件解析处理"""
        worker.wait_if_paused()
        self.gui.signals.log_signal.emit(
            f"正在处理文件: {os.path.basename(file_path)}", "info"
        )

        if file_path.endswith('.docx'):
            text = extract_text_from_docx(file_path)
            return [f"{p}\n" for p in text.split('\n')]  # 模拟段落列表
        elif file_path.endswith('.txt'):
            return extract_text_from_txt(file_path)
        else:
            raise ValueError("仅支持.docx或.txt格式")

    def _execute_translation(self, source_file, target_lang, style, values, file_hash, worker):
        """执行分块翻译"""
        # 文件解析优化点：避免二次读取文件导致的编码问题
        if source_file.endswith('.docx'):
            text = extract_text_from_docx(source_file)
        else:
            paragraphs = extract_text_from_txt(source_file)
            # 将段落列表合并为完整文本（保留原始换行符）
            text = ''.join(paragraphs)

        chunks = dynamic_split(
            text,
            target_lang,
            max_tokens=FILE_HANDLER_CONFIG["CHUNKING"]["DEFAULT_MAX_TOKENS"]
        )

        if not chunks:
            raise ValueError("文件内容为空或分块失败")

        self.gui.signals.log_signal.emit(f"已分块: {len(chunks)} 个文本块", "info")
        translated_chunks = []
        previous_chunk = ""
        current_model = values['-MODEL-']

        for i, chunk in enumerate(chunks, 1):
            worker.wait_if_paused()
            QApplication.processEvents()

            translated, model_used = self.engine.safe_translate(
                chunk,
                values['-LANG-'],
                style,
                values['-TEMP-'],
                current_model,
                file_hash,
                previous_chunk,
                log_callback=lambda msg: self.gui.signals.log_signal.emit(msg, "retry")
            )

            translated_chunks.append(translated)
            previous_chunk = chunk

            # 更新进度
            progress = int((i / len(chunks)) * 100)
            self.gui.signals.progress_signal.emit(progress)
            self.gui.signals.log_signal.emit(
                f"进度: {progress}% | 已翻译 {i}/{len(chunks)} 块", "info"
            )

        return translated_chunks

    def _save_result(self, values, translated_paragraphs, output_path):
        """保存翻译结果（段落列表）"""
        if values['-WORD-']:
            save_as_word(translated_paragraphs, output_path)
        else:
            save_as_txt(translated_paragraphs, output_path)

    def _generate_output_path(self, values):
        """生成输出路径"""
        output_dir = values['-OUTPUT-'] or os.path.dirname(values['-SOURCE-'])
        os.makedirs(output_dir, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(values['-SOURCE-']))[0]
        ext = '.docx' if values['-WORD-'] else '.txt'
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        return os.path.join(
            output_dir,
            f"{base_name}_translated_{timestamp}{ext}"
        )

    def _update_ui_success(self, output_path):
        """更新成功状态"""
        self.gui.signals.log_signal.emit(
            f"✅ 翻译完成！文件已保存至：\n{output_path}", "success"
        )
        self.gui.signals.progress_signal.emit(100)

    def _handle_process_error(self, error):
        """处理错误"""
        self.logger.error("翻译流程错误", exc_info=True)
        self.gui.signals.log_signal.emit(
            f"❌ 发生错误：{str(error)}", "error"
        )
        self.gui.signals.progress_signal.emit(0)
        raise

    def run(self):
        """启动主循环"""
        self.logger.info("[Main] 启动应用程序")
        sys.exit(self.qt_app.exec())


if __name__ == "__main__":
    app = Application()
    app.run()