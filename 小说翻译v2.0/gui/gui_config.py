# gui/config/gui_config.py
"""
该文件定义了图形用户界面 (GUI) 相关的样式、布局和图标路径等配置。
方便统一管理和修改界面的视觉表现。
"""

# 导入 pathlib 模块，用于处理文件路径
from pathlib import Path

# --- 基础路径配置 ---
# 获取当前文件所在的目录，并定义图标目录路径。
BASE_DIR = Path(__file__).parent.parent # 获取 gui 目录的路径
ICON_DIR = BASE_DIR / "icons"          # 定义图标文件所在的目录路径 (gui/icons)

# --- 日志类型配置 ---
# 定义不同日志类型在 GUI 日志区域显示的颜色和图标。
LOG_TYPES = {
    "info": {"color": "#333333", "icon": "ℹ️"},    # 普通信息
    "success": {"color": "#4CAF50", "icon": "✅"}, # 成功信息
    "warning": {"color": "#FFC107", "icon": "⚠️"}, # 警告信息
    "error": {"color": "#F44336", "icon": "❌"},   # 错误信息
    "cache": {"color": "#4A90E2", "icon": "💾"},   # 缓存命中信息
    "retry": {"color": "#FFA500", "icon": "🔄"}    # API 重试信息
}

# --- 控件样式配置 ---
# 使用 CSS-like 语法定义 PyQt6 控件的样式表。
# 这些样式将在 gui_interface.py 中应用到相应的控件上。
STYLES = {
    # 进度条样式
    "QProgressBar": """
        QProgressBar {{
            height: 20px;                       /* 进度条高度 */
            background: {surface};              /* 进度条背景色 (使用 surface 颜色) */
            border-radius: 10px;                /* 边框圆角 */
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {primary}, stop:1 #4A90E288); /* 进度条填充块的渐变色 */
            border-radius: 10px;                /* 填充块圆角 */
        }}
    """,

    # 分组框样式
    "QGroupBox": """
        QGroupBox {{
            border: 2px solid {accent};         /* 边框颜色和宽度 (使用 accent 颜色) */
            border-radius: 8px;                 /* 边框圆角 */
            margin-top: 10px;                   /* 顶部外边距，为标题留出空间 */
            padding-top: 15px;                  /* 顶部内边距，内容区域与标题的距离 */
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;          /* 标题基于外边距定位 */
            left: 10px;                         /* 标题距离左边框的距离 */
            color: {accent};                    /* 标题文字颜色 (使用 accent 颜色) */
            font: bold 12px;                    /* 标题字体加粗，大小 12px */
        }}
    """,

    # 按钮样式
    "QPushButton": """
        QPushButton {{
            background: {color};                /* 按钮背景色 (传入具体颜色) */
            color: white;                       /* 按钮文字颜色 */
            border-radius: 5px;                 /* 按钮圆角 */
            padding: 8px 15px;                  /* 按钮内边距 (上下 8px, 左右 15px) */
            min-width: 80px;                    /* 按钮最小宽度 */
        }}
        QPushButton:hover {{ background: {color}88; }} /* 鼠标悬停时背景色变淡 (增加透明度) */
        QPushButton:pressed {{ background: {color}; }} /* 鼠标按下时恢复原色 */
        QPushButton:disabled {{ background: #CCCCCC; }} /* 禁用状态下的背景色 */
    """,

    # 单行输入框样式
    "QLineEdit": """
        QLineEdit {{
            background: {surface};              /* 背景色 (使用 surface 颜色) */
            border: 1px solid {accent};         /* 边框颜色和宽度 (使用 accent 颜色) */
            border-radius: 5px;                 /* 边框圆角 */
            padding: 8px;                       /* 内边距 */
            color: {text};                      /* 文字颜色 (使用 text 颜色) */
        }}
        QLineEdit:focus {{ border: 2px solid {primary}; }} /* 获取焦点时的边框样式 (使用 primary 颜色) */
    """,

    # 下拉框样式
    "QComboBox": """
        QComboBox {{
            background: {surface};              /* 背景色 (使用 surface 颜色) */
            border: 1px solid {accent};         /* 边框颜色和宽度 (使用 accent 颜色) */
            border-radius: 5px;                 /* 边框圆角 */
            padding: 5px;                       /* 内边距 */
            color: {text};                      /* 文字颜色 (使用 text 颜色) */
            min-width: 120px;                   /* 最小宽度 */
        }}
        QComboBox::drop-down {{
            border: none;                       /* 下拉箭头的边框 */
            width: 20px;                        /* 下拉箭头的宽度 */
        }}
        QComboBox QAbstractItemView {{          /* 下拉列表视图的样式 */
            background: {surface};              /* 背景色 */
            color: {text};                      /* 文字颜色 */
        }}
    """,

    # 单选按钮样式
    "QRadioButton": """
        QRadioButton {{
            color: {text};                      /* 文字颜色 (使用 text 颜色) */
            spacing: 8px;                       /* 指示器和文字之间的间距 */
        }}
        QRadioButton::indicator {{              /* 指示器 (圆圈) 的样式 */
            width: 16px;                        /* 指示器宽度 */
            height: 16px;                       /* 指示器高度 */
            border: 2px solid {primary};        /* 指示器边框 (使用 primary 颜色) */
            border-radius: 8px;                 /* 指示器圆角 (使其成为圆形) */
        }}
        QRadioButton::indicator:checked {{      /* 选中状态下的指示器 */
            background: {primary};              /* 填充颜色 (使用 primary 颜色) */
        }}
    """
}

# --- 布局配置 ---
# 定义主窗口和特定控件的布局参数。
LAYOUT = {
    "main_window": {                        # 主窗口布局设置
        "min_size": (1000, 680),            # 主窗口最小尺寸 (宽度, 高度)
        "margins": (20, 20, 20, 20),        # 主布局的外边距 (上, 左, 下, 右)
        "spacing": 20                       # 主布局中控件之间的间距
    },
    "progress_bar": {                       # 进度条特定布局设置
        "height": 20,                       # 进度条高度
        "text_visible": False               # 是否显示进度条上的百分比文本 (注：实际样式在 STYLES 中控制)
    }
}