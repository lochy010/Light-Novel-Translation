# gui/config/gui_config.py
"""GUI样式配置文件"""
from pathlib import Path

# 基础路径配置
BASE_DIR = Path(__file__).parent.parent
ICON_DIR = BASE_DIR / "icons"

# 日志类型配置
LOG_TYPES = {
    "info": {"color": "#333333", "icon": "ℹ️"},
    "success": {"color": "#4CAF50", "icon": "✅"},
    "warning": {"color": "#FFC107", "icon": "⚠️"},
    "error": {"color": "#F44336", "icon": "❌"},
    "cache": {"color": "#4A90E2", "icon": "💾"},
    "retry": {"color": "#FFA500", "icon": "🔄"}
}

# 控件样式配置
STYLES = {
    "QProgressBar": """
        QProgressBar {{
            height: 20px;
            background: {surface};
            border-radius: 10px;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {primary}, stop:1 #4A90E288);
            border-radius: 10px;
        }}
    """,

    "QGroupBox": """
        QGroupBox {{
            border: 2px solid {accent};
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 15px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            color: {accent};
            font: bold 12px;
        }}
    """,

    "QPushButton": """
        QPushButton {{
            background: {color};
            color: white;
            border-radius: 5px;
            padding: 8px 15px;
            min-width: 80px;
        }}
        QPushButton:hover {{ background: {color}88; }}
        QPushButton:pressed {{ background: {color}; }}
        QPushButton:disabled {{ background: #CCCCCC; }}
    """,

    "QLineEdit": """
        QLineEdit {{
            background: {surface};
            border: 1px solid {accent};
            border-radius: 5px;
            padding: 8px;
            color: {text};
        }}
        QLineEdit:focus {{ border: 2px solid {primary}; }}
    """,

    "QComboBox": """
        QComboBox {{
            background: {surface};
            border: 1px solid {accent};
            border-radius: 5px;
            padding: 5px;
            color: {text};
            min-width: 120px;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background: {surface};
            color: {text};
        }}
    """,

    "QRadioButton": """
        QRadioButton {{ 
            color: {text};
            spacing: 8px;
        }}
        QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border: 2px solid {primary};
            border-radius: 8px;
        }}
        QRadioButton::indicator:checked {{
            background: {primary};
        }}
    """
}

# 布局配置
LAYOUT = {
    "main_window": {
        "min_size": (1000, 680),
        "margins": (20, 20, 20, 20),
        "spacing": 20
    },
    "progress_bar": {
        "height": 20,
        "text_visible": False
    }
}