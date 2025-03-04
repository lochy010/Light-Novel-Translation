# config/settings.py
"""系统全局配置参数"""
from docx.shared import Pt

# 路径配置
PATH_CONFIG = {
    "CACHE_FILE": "translation_cache.json",  # 缓存文件
    "API_KEY_FILE": "api_key.txt",          # API密钥文件
    "LOG_DIR": "logs",                      # 日志目录
    "ICON_DIR": "icons"                     # 图标目录
}

# API配置
API_CONFIG = {
    "BASE_URL": "https://api.deepseek.com",
    "TIMEOUT": 180,
    "MAX_RETRY": 3,                      # 最大重试次数
    "RETRY_WAIT_BASE": 0.5                # 重试等待时间基数
}

# GUI配置
GUI_CONFIG = {
    "COLORS": {
        "primary": "#4A90E2",
        "background": "#F5F5F5",
        "surface": "#FFFFFF",
        "accent": "#0050B3",
        "text": "#333333",
        "success": "#4CAF50",
        "warning": "#FFC107",
        "error": "#F44336",
        "cache": "#4A90E2",
        "retry": "#FFA500",
        "clear": "#FF5722"
    },
    "FONT": {
        "family": "微软雅黑",
        "size": 10
    }
}

# 翻译引擎配置
TRANSLATION_CONFIG = {
    "LANGUAGE_MAP": {
        "中文": "zh",
        "英文": "en",
        "日语": "ja",
        "韩语": "ko"
    },
    "STYLE_MAP": {
        "标准": "standard",
        "日式轻小说": "light_novel",
        "正式": "formal"
    },
    "MODEL_MAP": {
        "DeepSeek-V3": "deepseek-chat",
        "DeepSeek-R1": "deepseek-reasoner"
    },
    "CONTEXT_LENGTH": {  # 上下文最大长度
        "zh": 300,
        "en": 500,
        "ja": 400,
        "ko": 350
    }
}

PROMPT_CONFIG = {
    "BASE_PROMPT": {
        "zh": "请将以下文本翻译为中文：\n",
        "ja": "请严格按以下要求翻译为日语：\n",
        "en": "Please translate the following text into English:\n",
        "ko": "Please translate the following text into Korean:\n"
    },
    "STYLE_PROMPT": {
        "light_novel": (
            "仅输出翻译完成后的文本，"
            "准确传达原文含义，确保语句通顺自然，无违和感，"
            "采用日本二次元轻小说风格，使用口语化且夸张化的表达，保留原文语义但增强趣味性，"
            "人名也要翻译，并且人名的前后翻译要一致，"
            "保持原文语义但增强趣味性和感染力，"
            "敬称/专名：符合轻小说惯例，"
            "文化概念：自然转换或补充说明，"
            "分段：保留原文段落结构。\n\n"
        ),
        "formal": "请使用正式语气翻译，保持专业术语准确性。\n\n",
        "standard": ""
    },
    "LANG_SPECIFIC_PROMPT": {
        "ja": (
            "日语专项要求：\n"
            "人名也要翻译，并且人名的前后翻译要一致\n"
            "- 正确使用助词（は、が、を、に）\n"
            "- 区分です/ます体与普通体\n"
            "- 使用日本当用汉字\n"
            "标点符号：使用日语标准格式\n"
        ),
        "en": (
            "英语专项要求：\n"
            "- 正确使用冠词（a/an/the）\n"
            "- 保持时态一致性\n"
            "- 使用地道美式英语\n"
        ),
        "ko": (
            "韩语专项要求：\n"
            "- 正确使用敬语（-습니다/-아요）\n"
            "- 准确处理助词（은/는、이/가）\n"
        ),
        "zh": ""
    }
}

# 文件处理配置
FILE_HANDLER_CONFIG = {
    "CHUNKING": {
        "DEFAULT_MAX_TOKENS": 6000,       # 默认分块大小
        "ASIAN_BUFFER_FACTOR": 1.5,       # 亚洲语言缓冲系数
        "LANG_CONFIG": {                  # 语言特定配置
            "zh": {"sentence_end": r"(?<=[。！？…!?])", "connectors": []},
            "en": {"sentence_end": r"(?<=[.!?…])", "connectors": ["However", "Moreover"]},
            "ja": {"sentence_end": r"(?<=[。．！？…♪〜])", "connectors": ["しかし", "また", "そして", "ただし"]},
            "ko": {"sentence_end": r"(?<=[.!?…])", "connectors": []}
        }
    },
    "DOCX_STYLE": {  # Word文档样式
        "FONT_SIZE": Pt(12),
        "FONTS": {
            "western": "Times New Roman",
            "east_asian": "楷体"
        },
        "LINE_SPACING": 1,
        "INDENT": Pt(24)
    }
}