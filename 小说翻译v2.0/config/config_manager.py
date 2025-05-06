# config/config_manager.py
"""
该文件负责应用程序的配置管理，特别是 API 密钥的读取、验证以及相关路径配置的获取和校验。
主要功能包括：
- 安全地从文件读取 API 密钥。
- 验证配置项的有效性（如 API 密钥文件是否存在且非空）。
- 提供获取配置中定义的路径的功能。
- 验证并（尝试）创建配置文件中定义的必要目录。
- 定义和处理配置相关的错误。
"""

# 导入 os 模块，用于与操作系统交互，如检查文件/目录是否存在、创建目录等。
import os
# 导入 logging 模块，用于记录应用程序运行过程中的信息、警告和错误。
import logging

# 导入自定义的路径配置字典
# settings 模块包含了应用程序所需的各种配置常量
from config.settings import PATH_CONFIG

# --- 初始化模块级日志记录器 ---
# 获取一个名为 'config_manager' 的日志记录器实例。
# 日志的格式化将在主程序入口 (main.py) 中统一设置。
logger = logging.getLogger(__name__) # 使用当前模块名作为记录器名称

# --- 自定义配置验证异常 ---
class ConfigValidationError(Exception):
    """
    自定义异常类，用于表示在配置读取或验证过程中发生的错误。
    继承自 Python 内置的 Exception 类。
    """
    pass
# --- 结束自定义配置验证异常 ---

# --- API 密钥读取函数 ---
def read_api_key(file_path=None):
    """
    从指定的外部文件安全地读取 API 密钥。

    执行流程：
    1.  确定 API 密钥文件的最终路径（优先使用传入的 file_path，否则使用 PATH_CONFIG 中的默认路径）。
    2.  检查确定的文件路径是否存在。
    3.  如果文件存在，尝试以 UTF-8 编码读取文件内容。
    4.  验证读取到的内容是否为空。
    5.  如果内容非空，去除首尾空白字符后返回密钥。

    参数:
        file_path (str, optional): API 密钥文件的路径。如果为 None，则从 config.settings.PATH_CONFIG 中获取默认路径。默认为 None。

    返回:
        str: 读取到的 API 密钥字符串。

    异常:
        FileNotFoundError: 如果指定的或默认的 API 密钥文件不存在。
        ValueError: 如果文件内容为空或文件编码不是有效的 UTF-8。
        ConfigValidationError: 如果 PATH_CONFIG 中缺少 'API_KEY_FILE' 配置项。
        IOError: 如果在读取文件时发生权限问题或其他 IO 错误。
        Exception: 如果发生其他未预期的读取错误。
    """
    # --- 步骤 1: 确定文件路径 ---
    if file_path is None:
        # 如果未直接提供文件路径，则尝试从配置文件中获取
        try:
            file_path = PATH_CONFIG["API_KEY_FILE"]
            # 记录日志，说明使用的是默认路径
            logger.info(f"[API Key Read] 使用配置文件中指定的默认路径: {file_path}")
        except KeyError:
            # 如果配置文件中缺少 'API_KEY_FILE' 键，这是一个严重的配置错误
            err_msg = "配置项 'API_KEY_FILE' 在 PATH_CONFIG 中缺失。"
            # 记录严重错误日志
            logger.critical(f"[API Key Read] {err_msg}")
            # 抛出自定义配置验证错误，提示用户检查配置文件
            raise ConfigValidationError(f"关键配置项缺失: API_KEY_FILE。\n请检查 config/settings.py 文件。") from None
    else:
        # 如果提供了文件路径，则记录日志说明使用的是指定路径
        logger.info(f"[API Key Read] 使用指定的 API 密钥文件路径: {file_path}")

    # --- 步骤 2-5: 读取和验证文件 ---
    logger.info(f"[API Key Read] 尝试读取 API 密钥文件...")
    try:
        # 2. 检查文件是否存在
        if not os.path.exists(file_path):
             # 文件不存在是一个明确的错误，记录关键日志并抛出 FileNotFoundError
             err_msg = f"密钥文件不存在: {file_path}"
             logger.critical(f"[API Key Read] {err_msg}")
             raise FileNotFoundError(err_msg) # 明确抛出异常

        # 3. 读取文件内容 (使用 'with' 语句确保文件正确关闭)
        logger.debug(f"[API Key Read] 文件存在，尝试以 UTF-8 编码读取内容...")
        with open(file_path, 'r', encoding='utf-8') as f:
            # 读取文件所有内容，并移除首尾的空白字符（如换行符、空格）
            api_key = f.read().strip()
            # 4. 验证内容非空
            if not api_key:
                # 如果移除空白后内容为空，记录错误并抛出 ValueError
                err_msg = "API密钥文件内容为空。"
                logger.error(f"[API Key Read] {err_msg} (文件: {file_path})")
                raise ValueError(err_msg) # 文件内容为空是值错误

            # 5. 读取成功
            key_length = len(api_key)
            # 为了安全，只预览密钥的首尾部分（如果长度足够）
            key_preview = f"{api_key[:4]}...{api_key[-4:]}" if key_length > 8 else api_key
            # 记录成功读取的日志，包含长度和预览
            logger.info(f"[API Key Read] 成功读取到 API 密钥 (长度: {key_length}，预览: {key_preview})。")
            # 返回读取到的密钥
            return api_key

    except FileNotFoundError:
        # 这个异常是在前面 os.path.exists 检查后显式抛出的，这里只需重新抛出即可
        raise
    except UnicodeDecodeError as ude:
        # 处理文件不是 UTF-8 编码的情况
        err_msg = f"密钥文件编码格式错误，无法使用 UTF-8 解码: {ude}"
        logger.error(f"[API Key Read] {err_msg} (文件: {file_path})")
        # 抛出 ValueError，提示用户检查文件编码
        raise ValueError("密钥文件编码格式错误，请确保文件为 UTF-8 编码。") from ude
    except IOError as ioe:
        # 处理读取文件时可能发生的其他 IO 错误，如权限不足
        err_msg = f"读取 API 密钥文件时发生 IO 错误: {ioe}"
        logger.error(f"[API Key Read] {err_msg} (文件: {file_path})", exc_info=True) # 记录堆栈信息
        # 重新抛出原始的 IO 错误
        raise
    except Exception as e:
        # 捕获所有其他未预料到的异常
        err_msg = f"读取 API 密钥时发生未预期错误: {e}"
        logger.error(f"[API Key Read] {err_msg} (文件: {file_path})", exc_info=True) # 记录堆栈信息
        # 重新抛出原始异常
        raise
# --- 结束 API 密钥读取函数 ---

# --- 配置验证入口函数 ---
def validate_config():
    """
    作为配置验证的主要入口点，核心任务是验证 API 密钥是否可成功读取。

    执行流程：
    1.  调用 `read_api_key()` 函数尝试获取 API 密钥。`read_api_key` 内部会处理路径查找、文件读取和基本的内容验证。
    2.  如果 `read_api_key()` 成功返回密钥，则认为此部分的配置验证通过，并返回该密钥。
    3.  捕获 `read_api_key()` 可能抛出的各种异常（如 `FileNotFoundError`, `ValueError`, `ConfigValidationError`, `IOError`, `Exception`）。
    4.  将捕获到的底层异常包装成一个 `ConfigValidationError` 异常，并附带对用户更友好的错误提示信息，然后重新抛出。

    返回:
        str: 验证成功后，返回有效的 API 密钥字符串。

    异常:
        ConfigValidationError: 当 API 密钥读取失败或发生其他配置相关错误时抛出。异常消息会包含用户友好的提示。
                               注意：此函数不验证 API Key 本身是否能在 DeepSeek API 服务器上认证成功，
                               这通常需要实际的 API 调用来完成（例如通过 `TranslationEngine.test_api_connection()`）。
    """
    logger.info("[Config Validation] --- 开始配置验证流程 (主要验证 API 密钥) ---")
    try:
        # 调用 read_api_key 来获取并初步验证 API 密钥
        key = read_api_key()
        # 如果 read_api_key 没有抛出异常，说明密钥文件可读且非空
        logger.info("[Config Validation] API 密钥读取成功。")
        # 验证流程成功结束
        logger.info("[Config Validation] --- 配置验证流程成功 ---")
        # 返回成功读取的密钥
        return key
    except FileNotFoundError as e:
        # 处理文件未找到错误
        error_msg = f"密钥文件不存在: {str(e)}"
        user_friendly_msg = f"密钥加载失败\n{error_msg}\n请确认 api_key.txt 文件存在于指定位置。"
        # 记录关键错误日志
        logger.critical(f"[Config Validation] 验证失败: {error_msg}")
        # 包装成 ConfigValidationError 并重新抛出
        raise ConfigValidationError(user_friendly_msg) from e
    except ValueError as e:
        # 处理文件内容无效或编码错误
        error_msg = f"密钥文件内容或格式错误: {str(e)}"
        user_friendly_msg = f"密钥文件内容无效\n{error_msg}\n请检查 api_key.txt 文件内容是否为空或编码是否为 UTF-8。"
        # 记录关键错误日志
        logger.critical(f"[Config Validation] 验证失败: {error_msg}")
        # 包装成 ConfigValidationError 并重新抛出
        raise ConfigValidationError(user_friendly_msg) from e
    except ConfigValidationError as e:
        # 如果 read_api_key 内部因为配置缺失（如 API_KEY_FILE 未定义）抛出了 ConfigValidationError，
        # 则记录日志并直接重新抛出，保持原始错误信息。
        logger.critical(f"[Config Validation] 验证失败: {str(e)}")
        raise
    except Exception as e:
        # 捕获在 read_api_key 或此过程中可能发生的其他所有未知异常
        error_msg = f"读取或验证配置时发生未知错误: {str(e)}"
        user_friendly_msg = f"配置加载失败\n{error_msg}\n请检查系统权限、文件状态或查看日志获取详细信息。"
        # 记录关键错误日志，并包含堆栈信息
        logger.critical(f"[Config Validation] 验证失败: {error_msg}", exc_info=True)
        # 包装成 ConfigValidationError 并重新抛出
        raise ConfigValidationError(user_friendly_msg) from e
# --- 结束配置验证入口函数 ---

# 移除 show_error_message 函数 (已废弃)

# --- 获取配置路径函数 ---
def get_config_path(key):
    """
    从 config.settings.PATH_CONFIG 字典中获取指定键对应的路径配置项。

    参数:
        key (str): 需要获取的路径配置项的键名（例如 "LOG_DIR", "CACHE_FILE"）。

    返回:
        str: 与指定键关联的路径字符串。

    异常:
        ConfigValidationError: 如果指定的键在 PATH_CONFIG 字典中不存在，会记录关键错误并抛出此异常。
    """
    # 记录调试日志，说明正在尝试获取哪个键
    logger.debug(f"[Path Config] 尝试获取配置路径，键: '{key}'")
    try:
        # 尝试从 PATH_CONFIG 字典中获取值
        path_value = PATH_CONFIG[key]
        # 记录成功获取的日志
        logger.debug(f"[Path Config] 成功获取路径 '{key}': {path_value}")
        # 返回获取到的路径值
        return path_value
    except KeyError:
        # 如果字典中不存在该键，这是一个配置错误
        msg = f"配置路径键 '{key}' 不存在于 config/settings.py 的 PATH_CONFIG 中。"
        # 记录关键错误日志
        logger.critical(f"[Path Config] {msg}")
        # 抛出 ConfigValidationError，提示用户检查配置文件
        raise ConfigValidationError(f"关键配置项缺失: {key}。\n请检查 config/settings.py 文件。") from None
# --- 结束获取配置路径函数 ---

# --- 验证配置路径函数 ---
def validate_config_paths():
    """
    验证在 config.settings.PATH_CONFIG 中定义的关键目录路径是否存在。
    如果目录不存在，则尝试创建这些目录。

    执行流程：
    1.  获取日志目录路径 (`LOG_DIR`)，如果不存在则尝试创建。创建失败会抛出异常。
    2.  获取图标目录路径 (`ICON_DIR`)，如果不存在则尝试创建。创建失败仅记录警告，不中断程序。
    3.  获取缓存文件路径 (`CACHE_FILE`)，提取其所在目录，如果目录不存在且非当前目录，则尝试创建。创建失败会抛出异常。
    4.  获取 API 密钥文件路径 (`API_KEY_FILE`)，提取其所在目录，如果目录不存在且非当前目录，则尝试创建。创建失败会抛出异常。

    返回:
        bool: 如果所有必要的目录检查和创建（如果需要）都成功（或仅遇到非致命警告，如图标目录创建失败），则返回 True。

    异常:
        ConfigValidationError: 如果 PATH_CONFIG 中缺少关键路径配置项，或者无法创建必要的目录（如日志、缓存、API Key 目录），则抛出此异常。
    """
    logger.info("[Path Validation] --- 开始验证和准备配置路径 ---")
    try:
        # --- 1. 检查并创建日志目录 ---
        log_dir_key = "LOG_DIR"
        # 使用 get_config_path 获取路径，它会处理 KeyError
        log_dir = get_config_path(log_dir_key)
        logger.info(f"[Path Validation] 检查日志目录: {log_dir}")
        # 检查目录是否存在
        if not os.path.exists(log_dir):
            logger.warning(f"[Path Validation] 日志目录不存在，尝试创建...")
            try:
                # 尝试创建目录，包括任何必要的父目录
                os.makedirs(log_dir)
                logger.info(f"[Path Validation] 成功创建日志目录: {log_dir}")
            except OSError as e:
                # 如果创建失败（例如权限问题），记录关键错误并抛出 ConfigValidationError
                msg = f"无法创建日志目录 '{log_dir}': {e}"
                logger.critical(f"[Path Validation] {msg}", exc_info=True)
                raise ConfigValidationError(f"日志目录创建失败\n{msg}\n请检查程序权限或磁盘空间。") from e
        else:
             # 如果目录已存在，记录信息日志
             logger.info(f"[Path Validation] 日志目录已存在。")

        # --- 2. 检查并创建图标目录 ---
        icon_dir_key = "ICON_DIR"
        icon_dir = get_config_path(icon_dir_key)
        logger.info(f"[Path Validation] 检查图标目录: {icon_dir}")
        if not os.path.exists(icon_dir):
            logger.warning(f"[Path Validation] 图标目录不存在，尝试创建...")
            try:
                os.makedirs(icon_dir)
                logger.info(f"[Path Validation] 成功创建图标目录: {icon_dir}")
            except OSError as e:
                # 图标目录创建失败通常不影响核心功能，记录警告即可，不抛出异常
                logger.warning(f"[Path Validation] 无法创建图标目录 '{icon_dir}'，可能导致图标无法显示: {e}")
        else:
            logger.info(f"[Path Validation] 图标目录已存在。")

        # --- 3. 检查并创建缓存文件所在目录 ---
        cache_file_key = "CACHE_FILE"
        cache_file_path = get_config_path(cache_file_key)
        # 获取缓存文件所在的目录路径
        cache_dir = os.path.dirname(cache_file_path)
        # 检查 cache_dir 是否为空字符串。如果为空，表示缓存文件在当前工作目录下，无需创建。
        if cache_dir:
            logger.info(f"[Path Validation] 检查缓存文件所在目录: {cache_dir}")
            if not os.path.exists(cache_dir):
                logger.warning(f"[Path Validation] 缓存目录不存在，尝试创建...")
                try:
                    os.makedirs(cache_dir)
                    logger.info(f"[Path Validation] 成功创建缓存目录: {cache_dir}")
                except OSError as e:
                     # 无法创建缓存目录是严重问题，记录关键错误并抛出异常
                     msg = f"无法创建缓存目录 '{cache_dir}': {e}"
                     logger.critical(f"[Path Validation] {msg}", exc_info=True)
                     raise ConfigValidationError(f"缓存目录创建失败\n{msg}\n请检查程序权限或磁盘空间。") from e
            else:
                logger.info(f"[Path Validation] 缓存目录已存在。")
        else:
             # 如果缓存文件配置在当前目录，记录信息
             logger.info(f"[Path Validation] 缓存文件配置在当前目录，无需检查或创建特定目录。")

        # --- 4. 检查并创建 API Key 文件所在目录 ---
        api_key_file_key = "API_KEY_FILE"
        api_key_file_path = get_config_path(api_key_file_key)
        # 获取 API Key 文件所在的目录路径
        api_key_dir = os.path.dirname(api_key_file_path)
        # 检查 api_key_dir 是否为空字符串。如果为空，表示文件在当前目录下。
        if api_key_dir:
            logger.info(f"[Path Validation] 检查 API Key 文件所在目录: {api_key_dir}")
            if not os.path.exists(api_key_dir):
                logger.warning(f"[Path Validation] API Key 目录不存在，尝试创建...")
                try:
                    os.makedirs(api_key_dir)
                    logger.info(f"[Path Validation] 成功创建 API Key 目录: {api_key_dir}")
                except OSError as e:
                     # 无法创建 API Key 目录可能是严重问题（例如用户无法放置密钥文件）
                     msg = f"无法创建 API Key 文件所在目录 '{api_key_dir}': {e}"
                     logger.critical(f"[Path Validation] {msg}", exc_info=True)
                     raise ConfigValidationError(f"API Key 目录创建失败\n{msg}\n请检查程序权限或磁盘空间。") from e
            else:
                logger.info(f"[Path Validation] API Key 目录已存在。")
        else:
             # 如果 API Key 文件配置在当前目录，记录信息
             logger.info(f"[Path Validation] API Key 文件配置在当前目录，无需检查或创建特定目录。")

        # 如果所有检查和必要的创建都通过（或仅遇到非致命警告）
        logger.info("[Path Validation] --- 配置路径验证和准备成功 ---")
        return True # 表示成功

    except ConfigValidationError as e:
        # 捕获由 get_config_path 或目录创建失败抛出的 ConfigValidationError
        logger.critical(f"[Path Validation] --- 配置路径验证失败: {str(e)} ---")
        raise # 直接重新抛出，让调用者（如 Application 初始化）处理
    except Exception as e:
        # 捕获在此验证过程中发生的其他所有未知异常
        logger.critical(f"[Path Validation] 配置路径验证过程中发生未知错误: {e}", exc_info=True)
        logger.critical("[Path Validation] --- 配置路径验证失败 (未知错误) ---")
        # 包装成 ConfigValidationError 抛出
        raise ConfigValidationError(f"配置路径验证失败\n发生未知错误: {e}") from e
# --- 结束验证配置路径函数 ---