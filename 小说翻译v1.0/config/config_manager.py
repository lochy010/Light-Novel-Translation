# config\config_manager.py
"""
配置管理模块
功能：负责API密钥的读取、验证和配置管理
核心机制：
- 提供安全的API密钥文件读取流程
- 实现配置验证与错误处理机制
- 集成GUI错误提示与日志记录
- 支持异常情况下的友好用户反馈
"""

import os
import logging
import tkinter as tk
from tkinter import messagebox

# 导入配置文件
from config.settings import PATH_CONFIG

# 初始化模块级日志器
logger = logging.getLogger("ConfigManager")


def read_api_key(file_path=None):
    """从外部文件安全读取API密钥

    功能流程：
    1. 检查文件是否存在
    2. 验证文件内容非空
    3. 返回去除首尾空格的密钥

    :param file_path: API密钥文件路径，默认为api_key.txt
    :return: 字符串形式的API密钥
    :raises FileNotFoundError: 文件不存在时抛出
    :raises ValueError: 文件内容为空时抛出
    """
    # 使用配置文件中的默认路径
    if file_path is None:
        file_path = PATH_CONFIG["API_KEY_FILE"]

    logger.info(f"正在读取API密钥文件: {file_path}")
    try:
        # 使用with语句确保文件正确关闭
        with open(file_path, 'r', encoding='utf-8') as f:
            api_key = f.read().strip()
            # 验证密钥非空
            if not api_key:
                logger.error("API密钥文件内容为空")
                raise ValueError("API密钥文件内容为空")
            logger.debug("成功读取到有效API密钥")
            return api_key
    except FileNotFoundError:
        # 文件不存在时的关键错误处理
        logger.critical(f"密钥文件不存在: {file_path}")
        raise
    except UnicodeDecodeError:
        # 处理文件编码问题
        logger.error("文件编码格式不兼容")
        raise ValueError("密钥文件编码格式错误")
    except Exception as e:
        # 捕获其他未知异常
        logger.error("读取API密钥时发生未预期错误", exc_info=True)
        raise


def validate_config():
    """配置验证入口函数

    执行流程：
    1. 调用read_api_key获取密钥
    2. 成功返回密钥字符串
    3. 失败时弹出GUI错误提示并退出程序

    :return: 验证成功的API密钥字符串
    """
    logger.info("启动配置验证流程")
    try:
        key = read_api_key()
        logger.info("配置验证成功，密钥有效")
        return key
    except FileNotFoundError as e:
        # 文件不存在时的用户提示
        error_msg = f"密钥文件不存在：{str(e)}"
        logger.critical(error_msg)
        show_error_message(f"密钥加载失败\n{error_msg}\n请确认api_key.txt文件存在", "关键错误")
        exit(1)
    except ValueError as e:
        # 文件内容错误处理
        error_msg = f"密钥格式错误：{str(e)}"
        logger.critical(error_msg)
        show_error_message(f"密钥文件内容无效\n{error_msg}\n请检查文件内容格式", "配置错误")
        exit(1)
    except Exception as e:
        # 通用错误处理
        error_msg = f"未知配置错误：{str(e)}"
        logger.critical("配置验证失败", exc_info=True)
        show_error_message(f"配置加载失败\n{error_msg}\n请检查系统配置", "系统错误")
        exit(1)


def show_error_message(message, title):
    """使用tkinter弹出错误对话框
    新增功能：支持从GUI配置中读取颜色设置

    :param message: 错误消息内容
    :param title: 对话框标题
    """
    root = tk.Tk()  # 创建一个根窗口
    root.withdraw()  # 隐藏主窗口
    messagebox.showerror(title, message)  # 显示错误对话框
    root.destroy()  # 销毁根窗口


def get_config_path(key):
    """新增方法：获取配置路径
    功能：从配置文件中获取指定路径配置项

    :param key: 配置键名
    :return: 配置路径字符串
    :raises KeyError: 配置项不存在时抛出
    """
    try:
        return PATH_CONFIG[key]
    except KeyError:
        logger.error(f"配置路径不存在: {key}")
        raise


def validate_config_paths():
    """新增方法：验证配置路径
    功能：检查所有配置路径是否有效，创建必要的目录

    :return: 布尔值，表示所有路径是否有效
    """
    try:
        # 检查日志目录
        log_dir = get_config_path("LOG_DIR")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            logger.info(f"创建日志目录: {log_dir}")

        # 检查图标目录
        icon_dir = get_config_path("ICON_DIR")
        if not os.path.exists(icon_dir):
            os.makedirs(icon_dir)
            logger.info(f"创建图标目录: {icon_dir}")

        return True
    except Exception as e:
        logger.error(f"配置路径验证失败: {str(e)}")
        return False