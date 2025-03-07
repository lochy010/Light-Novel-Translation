# 轻小说翻译系统功能说明文档

## 项目概述

本项目目前是一个基于**DeepSeekAPI**的轻小说翻译软件，也支持多语言的文档翻译，具备缓存管理、重试和UI界面。该项目主要是自己想用来翻译pixiv上小说之类的，代码主要由AI完成，目前主要对轻小说的翻译做了优化，如有需要修改的地方可以自行随意修改。

## 使用方法

### 启动系统

- **首次运行前请将个人申请的API密钥复制到api_key.txt中，密钥可以到DeepSeek开放平台自行申请,API需要付费，请根据需要自行决定（我记得最低是1块钱）。（如果你想分享给别人，记得先把api_key.txt中你的密钥删掉，要不然一起给别人了）**
- ![image](https://github.com/user-attachments/assets/cc7838ee-b1a2-4321-904c-1ef5a9a3cabb)

- **双击DocTranslator.exe启动程序。**

### 用户界面

- **文件选择**：点击“选择文件”按钮，选择要翻译的文档（支持.docx和.txt格式）。
- **输出配置**：设置输出路径、输出格式（Word或TXT）、目标语言、翻译风格、模型选择和温度值。
- **翻译控制**：点击“开始翻译”按钮启动翻译任务，点击“暂停”按钮暂停任务，点击“清除缓存”按钮清空所有缓存。

### 日志与进度

- **实时日志**：翻译过程中，日志会实时显示在右侧的日志面板中，包括缓存命中和翻译进度等。
- **进度条**：显示翻译任务的进度百分比。

### 重要

- **如果你想分享给别人，记得先把api_key.txt中你的密钥删掉，要不然一起给别人了**
- **缓存记得清，缓存保存在translation_cache.json中，不及时清理的话分享出去别人会看到**

## 主要功能模块

### 缓存管理模块 (`cache_manager.py`)

- **功能描述**：
  - 实现缓存管理，支持缓存生命周期管理、自动清理和跨会话隔离。
  - 提供缓存命中检测、清理和会话关联管理。
- **核心机制**：
  - 使用线程安全的锁机制保证并发安全。
  - 支持JSON文件持久化存储缓存数据。
  - 基于文件哈希实现会话级缓存隔离。
- **主要接口**：
  - `get_key(text, lang, style, file_hash)`: 生成唯一缓存键。
  - `get(text, lang, style, file_hash)`: 获取缓存内容。
  - `set(text, lang, style, translation, file_hash)`: 设置缓存内容。
  - `purge_session_cache(file_hash)`: 清理指定会话的全部缓存。
  - `clear_all_cache()`: 清空所有缓存数据。

### 2.2 配置管理模块 (`config_manager.py`)

- **功能描述**：
  - 负责API密钥的读取、验证和配置管理。
  - 提供API密钥文件读取流程，支持配置验证与错误处理机制。
- **核心机制**：
  - 使用配置文件中的默认路径读取API密钥。
  - 集成GUI错误提示与日志记录。
- **主要接口**：
  - `read_api_key(file_path)`: 从外部文件安全读取API密钥。
  - `validate_config()`: 验证配置并返回API密钥。
  - `show_error_message(message, title)`: 弹出错误对话框。
  - `get_config_path(key)`: 获取配置路径。
  - `validate_config_paths()`: 验证配置路径并创建必要的目录。

### 2.3 文件处理模块 (`file_handler.py`)

- **功能描述**：
  - 实现文档的智能分块、格式解析和输出保存。
  - 支持DOCX/TXT格式的解析与生成，动态分块算法适配多语言特性。
- **核心机制**：
  - 自动检测文件编码格式。
  - 保留文档结构并生成符合排版规范的输出文件。
- **主要接口**：
  - `get_file_hash(file_path)`: 生成文件唯一特征码（MD5哈希值）。
  - `dynamic_split(text, target_lang, max_tokens)`: 动态分块算法。
  - `extract_text_from_docx(docx_path)`: 解析DOCX文档内容。
  - `extract_text_from_txt(txt_path)`: 解析TXT文档内容。
  - `save_as_word(content, output_path)`: 生成符合排版规范的Word文档。
  - `save_as_txt(content, output_path)`: 生成标准TXT文档。

### 2.4 GUI界面模块 (`gui_interface.py`)

- **功能描述**：
  - 提供用户交互界面，管理翻译任务流程，实现多线程任务管理与通信。
  - 实时日志显示与进度监控，文件选择与参数配置界面。
- **核心机制**：
  - 使用PyQt6构建UI。
- **主要接口**：
  - `TranslationGUI(application)`: 主GUI窗口类。
  - `start_translation()`: 触发翻译流程。
  - `toggle_pause()`: 切换暂停/继续状态。
  - `clear_cache()`: 清除缓存事件处理。

### 2.5 翻译引擎模块 (`translation_engine.py`)

- **功能描述**：
  - 实现翻译业务逻辑，集成AI翻译API，管理翻译上下文。
  - 提供错误重试机制和模型降级策略，支持格式保留和缓存优化。
- **核心机制**：
  - 集成DeepSeek翻译API，支持多语言、多风格翻译。
  - 实现带上下文的翻译流程，保留和恢复文本格式。
- **主要接口**：
  - `translate_with_context(text, target_lang, style, temperature, model_name, file_hash)`: 带上下文的翻译核心方法。
  - `safe_translate(text, target_lang, style, temp, model_name, file_hash)`: 增强安全性的翻译方法。
  - `preserve_formatting(text, target_lang)`: 增强格式保留方法。
  - `restore_formatting(translated_text, replacements, target_lang)`: 还原格式。
