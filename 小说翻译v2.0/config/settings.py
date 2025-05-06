# config/settings.py
"""
该文件定义了应用程序所需的各种全局配置参数。
包括文件路径、API设置、GUI样式、翻译引擎参数、提示词模板以及文件处理选项等。
"""

# 导入 docx 库中用于设置字号的 Pt 类
from docx.shared import Pt

# --- 路径配置 ---
# 定义应用程序中使用的各种文件和目录的路径。
PATH_CONFIG = {
    "CACHE_FILE": "translation_cache.json",  # 缓存文件的名称，用于存储翻译结果和会话映射
    "API_KEY_FILE": "api_key.txt",          # 存储 DeepSeek API 密钥的文件名
    "LOG_DIR": "logs",                      # 存储日志文件的目录名
    "ICON_DIR": "icons"                     # 存储 GUI 图标文件的目录名
}

# --- API 配置 ---
# 定义与 DeepSeek API 交互相关的参数。
API_CONFIG = {
    "BASE_URL": "https://api.deepseek.com", # DeepSeek API 的基础 URL
    "TIMEOUT": 180,                         # API 请求的超时时间（秒）
    "MAX_RETRY": 3,                         # API 请求失败时的最大重试次数
    "RETRY_WAIT_BASE": 5                    # 重试等待时间基数（秒），每次重试等待时间会加倍
}

# --- GUI 配置 ---
# 定义图形用户界面的颜色主题和字体设置。
GUI_CONFIG = {
    "COLORS": {                             # 定义界面元素的颜色
        "primary": "#4A90E2",               # 主要颜色，用于按钮、进度条等
        "background": "#F5F5F5",            # 应用程序背景色
        "surface": "#FFFFFF",               # 控件表面颜色，如输入框、列表背景
        "accent": "#0050B3",                # 强调色，用于边框、标题等
        "text": "#333333",                  # 主要文本颜色
        "success": "#4CAF50",               # 成功状态颜色，用于日志、按钮等
        "warning": "#FFC107",               # 警告状态颜色
        "error": "#F44336",                 # 错误状态颜色
        "cache": "#4A90E2",                 # 缓存命中日志颜色
        "retry": "#FFA500",                 # 重试日志颜色
        "clear": "#FF5722"                  # 清除缓存按钮颜色
    },
    "FONT": {                               # 定义界面字体
        "family": "微软雅黑",               # GUI 界面使用的字体族
        "size": 10                          # GUI 界面使用的字体大小 (单位: point)
    }
}

# --- 翻译引擎配置 ---
# 定义翻译引擎相关的语言、风格、模型映射以及上下文长度限制。
TRANSLATION_CONFIG = {
    "LANGUAGE_MAP": {                       # 语言名称到 API 语言代码的映射
        "中文": "zh",
        "英文": "en",
        "日语": "ja",
        "韩语": "ko"
    },
    "STYLE_MAP": {                          # 翻译风格名称到 API 风格代码或标识的映射
        "标准": "standard",                 # 标准风格
        "日式轻小说": "light_novel",         # 日式轻小说风格
        "正式": "formal",                   # 正式风格
        "通用": "custom"                    # 通用/自定义风格，允许用户提供提示词
    },
    "MODEL_MAP": {                          # 用户界面模型名称到 API 模型标识符的映射
        "DeepSeek-V3": "deepseek-chat",     # 对应 API 的 chat 模型
        "DeepSeek-R1": "deepseek-reasoner"  # 对应 API 的 reasoner 模型 (如果适用)
    },
    "CONTEXT_LENGTH": {                     # 不同语言的上下文最大长度限制 (字符数)
        "zh": 300,                          # 中文上下文长度
        "en": 500,                          # 英文上下文长度
        "ja": 400,                          # 日语上下文长度
        "ko": 350                           # 韩语上下文长度
    }
}

# --- 提示词配置 ---
# 定义用于构建 API 请求的提示词模板。
PROMPT_CONFIG = {
    "BASE_PROMPT": {                        # 各种目标语言的基础翻译指令
        "zh": "请将以下文本翻译为中文：\n",
        "ja": "请严格按以下要求翻译为日语：\n",
        "en": "Please translate the following text into English:\n",
        "ko": "Please translate the following text into Korean:\n"
    },
    "STYLE_PROMPT": {                       # 不同预设翻译风格的附加指令
        "light_novel": (                   # 日式轻小说风格的详细要求
            "仅输出翻译完成后的文本，"
            "准确传达原文含义，确保语句通顺自然，无违和感，但不要改变某些词语意思，"
            "采用日本二次元轻小说风格，使用口语化且夸张化的表达，保留原文语义但增强趣味性，"
            "人名和语气词要翻译，并且人名的前后翻译要一致，"
            "保持原文语义但增强趣味性和感染力，"
            "敬称/专名：符合轻小说惯例，"
            "文化概念：自然转换或补充说明，"
            "分段：保留原文段落结构。\n\n"
        ),
        "formal": "请使用正式语气翻译，保持专业术语准确性。\n\n", # 正式风格的要求
        "standard": "",                      # 标准风格无特定附加指令
        "custom": ""                         # 通用/自定义风格，由用户提供提示词
    },
    "LANG_SPECIFIC_PROMPT": {               # 针对特定目标语言的专项要求
        "ja": (                            # 日语的额外要求
            "日语专项要求：\n"
            "人名要翻译，并且人名的前后翻译要一致\n"
            "正确使用助词（は、が、を、に）\n"
            "区分です/ます体与普通体\n"
            "使用日本当用汉字\n"
            "标点符号：使用日语标准格式\n"
        ),
        "en": (                            # 英语的额外要求
            "英语专项要求：\n"
            "正确使用冠词（a/an/the）\n"
            "保持时态一致性\n"
            "使用地道美式英语\n"
        ),
        "ko": (                            # 韩语的额外要求
            "韩语专项要求：\n"
            "正确使用敬语（-습니다/-아요）\n"
            "准确处理助词（은/는、이/가）\n"
        ),
        "zh": (                            # 中文的额外要求
            "中文专项要求：\n"
            "标点符号：请使用标准的中文标点符号（例如：。，、？！「」『』）。\n"
            "专有名词：外国人名、地名、组织名等保持全文一致。\n"
            "文化习语：对于原文中的文化特定概念或习语，若中文无对应说法，请进行意译或在必要时简短注释，确保中国读者能理解。\n"
        )
    }
}

# --- 文件处理配置 ---
# 定义文件处理相关的参数，如分块大小、缓冲区和 Word 文档样式。
FILE_HANDLER_CONFIG = {
    "CHUNKING": {                           # 智能分块算法的配置
        "DEFAULT_MAX_TOKENS": 6000,         # 默认的最大分块大小（按字节数估算，非严格 token 数）
        "ASIAN_BUFFER_FACTOR": 1.5,         # 亚洲语言（中日韩）的缓冲系数，用于调整估算的字节数限制
        "LANG_CONFIG": {                    # 语言特定的分句规则和连接词配置
            "zh": {"sentence_end": r"[。！？…!?]", "connectors": []}, # 中文句末标点和连接词
            "en": {"sentence_end": r"[.!?…]", "connectors": ["However", "Moreover"]}, # 英文句末标点和连接词
            "ja": {"sentence_end": r"[。．！？…♪〜]", "connectors": ["しかし", "また", "そして", "ただし"]}, # 日文句末标点和连接词
            "ko": {"sentence_end": r"[.!?…]", "connectors": []} # 韩文句末标点和连接词
        }
    },
    "DOCX_STYLE": {                         # 输出 Word 文档 (.docx) 的样式配置
        "FONT_SIZE": Pt(12),                # 默认字号 (12磅)
        "FONTS": {                          # 默认字体设置
            "western": "Calibri",           # 西文字符（拉丁字母等）使用的字体
            "east_asian": "Microsoft YaHei" # 东亚字符（中日韩）使用的字体 (微软雅黑)
        },
        "LINE_SPACING": 1,                  # 行距 (1 表示单倍行距)
        "INDENT": Pt(24)                    # 段落首行缩进 (24磅，约等于12磅字体的2个字符宽度)
    }
}