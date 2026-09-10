# =====1、引入的库====
import os
import sys
import psutil
from flask import Flask, render_template, redirect, url_for, request, flash, send_file, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from io import BytesIO
import re
from datetime import datetime
import pandas as pd
import time
import openpyxl
import warnings
from openpyxl import reader, load_workbook
import zipfile
from dateutil.relativedelta import relativedelta
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment
from typing import Dict
import platform
import subprocess
import shutil
from waitress import serve
import importlib.util
import logging
from version import APP_NAME, VERSION, version_text

# ========== 调试日志控制（独立于预加载模式） ==========
DEBUG_MODE = os.getenv('NETASSIST_DEBUG', 'false').lower() == 'true'
if DEBUG_MODE:
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
    # 可选：同时开启 Werkzeug 的调试日志，方便看请求详情
    logging.getLogger('werkzeug').setLevel(logging.DEBUG)

else:
    # 生产模式下，仅显示 WARNING 及以上级别的日志（保持控制台干净）
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout)
    # logging.getLogger('werkzeug').setLevel(logging.WARNING)

def load_module_from_path(file_path, module_alias=None):
    """
    从任意文件路径加载 Python 模块，返回模块对象。
    :param file_path: .py 文件的绝对或相对路径
    :param module_alias: 指定加载后在 sys.modules 中存放的名称（可选），
                         不指定则自动从文件名生成（去除扩展名，替换非法字符为下划线）
    :return: 加载后的模块对象
    """
    # 确保文件存在
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 如果该模块已经加载过，直接返回
    if module_alias in sys.modules:
        return sys.modules[module_alias]

    # 使用 importlib 加载
    spec = importlib.util.spec_from_file_location(module_alias, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_alias] = module
    spec.loader.exec_module(module)
    return module



# 关闭openpyxl的DrawingML相关警告
warnings.filterwarnings("ignore", category=UserWarning, module=reader.drawings.__name__)

def check_port_in_use(host, port):
    """检查指定端口是否有进程在监听，返回 (是否占用, 占用进程信息)"""
    for conn in psutil.net_connections(kind='inet'):
        if conn.status == 'LISTEN' and conn.laddr.port == port and conn.laddr.ip == host:
            try:
                process = psutil.Process(conn.pid)
                return True, f"PID: {conn.pid}, 名称: {process.name()}"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return True, f"PID: {conn.pid}, 名称: [无法获取]"
    return False, None

def resource_path(relative_path):
    """获取资源的绝对路径，兼容开发环境和 PyInstaller 打包后的环境"""
    if getattr(sys, 'frozen', False):
        # 打包后运行，资源被解压到此路径
        base_path = sys._MEIPASS
    else:
        # 开发环境运行
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


# 有resource_path 就必须在打包时加--add-data命令，否则会报错，提示资源不存在
# 加载外部模块（实际文件名，别名）
CE_L2_MODULE = resource_path("imported_mods/py_CE脚本批量生成v1.2_基线&二层场景.py")
CE_L3_MODULE = resource_path("imported_mods/py_CE脚本批量生成v1.9_三层场景.py")
STATIC_MODULE = resource_path("imported_mods/py_CE静态路由批量生成v1.3.py")
VSYS_MODULE = resource_path("imported_mods/py_FW脚本批量生成v1.9_虚墙场景.py")
CLOUD_MODULE = resource_path("imported_mods/py_L3GW自定义云专线批量生成v1.4.py")
ce_L2_process = load_module_from_path(CE_L2_MODULE, "CE_L2_MODULE")
ce_L3_process = load_module_from_path(CE_L3_MODULE, "CE_L3_MODULE")
static_process = load_module_from_path(STATIC_MODULE, "STATIC_MODULE")  
vsys_process = load_module_from_path(VSYS_MODULE, "VSYS_MODULE")
cloud_process = load_module_from_path(CLOUD_MODULE, "CLOUD_MODULE")


# =====2、初始化应用====
app = Flask(__name__, template_folder=resource_path('html'))
# 获取当前文件目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# print(f"[Info] 当前页面存放目录: {app.template_folder}")
# 自定义模板目录，添加asset子目录
template_dir = resource_path('html')
# template_dir = os.path.join(current_dir, 'html')
asset_template_dir = os.path.join(template_dir, 'asset')
topology_template_dir = os.path.join(template_dir, 'topology')
work_template_dir = os.path.join(template_dir, 'work')

# 将asset等目录添加到模板目录列表，其中jinja_loader是Flask内置的Jinja模板加载器，负责查找和加载模板文件（如HTML文件）
app.jinja_loader.searchpath.append(asset_template_dir)
app.jinja_loader.searchpath.append(topology_template_dir)
app.jinja_loader.searchpath.append(work_template_dir)

# 配置Flask应用的密钥，用于完成会话管理、密码哈希签名等安全相关操作
_default_secret_key = 'dev_secret_key_should_be_changed'
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', _default_secret_key)
if app.config['SECRET_KEY'] == _default_secret_key:
    print("[Warning] FLASK_SECRET_KEY 环境变量未设置，当前使用默认开发密钥。生产环境请务必设置 FLASK_SECRET_KEY 以保障会话安全。")

# 限制上传文件最大 50MB，防止大文件 DoS
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

def safe_upload_filename(filename):
    """安全处理上传文件名，防止路径穿越，兼容中文文件名。
    优先使用 werkzeug.secure_filename；若结果为空（如纯中文），则回退到basename + 字符过滤。
    """
    if not filename:
        return 'uploaded_file'
    cleaned = secure_filename(filename)
    if cleaned:
        return cleaned
    # 回退：去掉路径部分，移除路径分隔符和穿越字符
    cleaned = os.path.basename(filename)
    cleaned = cleaned.replace('..', '').replace('/', '').replace('\\', '').replace('\x00', '')
    return cleaned if cleaned else 'uploaded_file'

# 使中文正常渲染
app.config['JSON_AS_ASCII'] = False

# 获取可执行文件所在目录（用于可写文件夹）
if getattr(sys, 'frozen', False):
    base_writeable_path = os.path.dirname(sys.executable)
else:
    base_writeable_path = os.path.abspath(".")


RESULTS_FOLDER = 'generated_scripts'
# 配置文件上传路径和允许的文件类型
app.config['ASSET_INFO_FOLDER'] = os.path.join(base_writeable_path, 'asset_info')
app.config['TEMPLATE_UPLOAD_FOLDER'] = os.path.join(base_writeable_path, 'templates_uploads')
app.config['DATA_UPLOAD_FOLDER'] = os.path.join(base_writeable_path, 'data_uploads')
app.config['RESULTS_FOLDER'] = os.path.join(base_writeable_path, RESULTS_FOLDER)
TEMPLATE_EXT_DIR = 'templates_uploads'
data_upload_dir = app.config['DATA_UPLOAD_FOLDER']
# 自定义云专线文件存储目录（可自由修改）
app.config['CUSTOM_LINE_FOLDER'] = os.path.join(data_upload_dir, 'custom_line_uploads')

# 资产信息文件允许的扩展名
app.config['ALLOWED_ASSET_INFO_EXTENSIONS'] = {'json', 'xlsx'}
app.config['ALLOWED_CUSTOM_LINE_EXTENSIONS'] = {'txt', 'log'}  # 按需调整允许的扩展名
app.config['ALLOWED_TEMPLATE_EXTENSIONS'] = {'txt', 'cfg'}
app.config['ALLOWED_DATA_EXTENSIONS'] = {'xlsx', 'xls'}
app.config['ALLOWED_DEVICE_MAPPING_EXTENSIONS'] = {'json'}




# 确保上传目录存在，若不存在则自动创建
os.makedirs(app.config['ASSET_INFO_FOLDER'], exist_ok=True)
os.makedirs(app.config['TEMPLATE_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DATA_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)
os.makedirs(app.config['CUSTOM_LINE_FOLDER'], exist_ok=True)


# ===================== 核心配置项（可根据业务灵活调整） =====================

# 配置文件路径（放在可写根目录）
GLOBAL_EXCEL_INFO = '设备清单及拓扑映射表_示例.txt'
GLOBAL_EXCEL_INFO_PATH = os.path.join(app.config['ASSET_INFO_FOLDER'], GLOBAL_EXCEL_INFO)
GLOBAL_DEVICE_INFO = "设备名称映射表_示例.json"
GLOBAL_DEVICE_INFO_PATH = os.path.join(app.config['ASSET_INFO_FOLDER'], GLOBAL_DEVICE_INFO)
# 默认文件名（硬编码，作为回退值）
DEFAULT_EXCEL_FILENAME = "设备维护清单_示例.xlsx"
DEFAULT_LLDP_FILENAME = "设备信息及互联表_示例.xlsx"



# Excel文件路径配置
EXCEL_DIR = "asset_info"
EXCEL_FILENAME = DEFAULT_EXCEL_FILENAME
EXCEL_PATH = resource_path(os.path.join(EXCEL_DIR, EXCEL_FILENAME))
# sn映射字典，用于根据lldp设备信息表中的sn到总清单查询对应列值
RELATE_SHEET_NAME = "设备清单"  # 第二个Excel的指定Sheet（按需修改）
RELATE_NAME_COL = "设备名称"
RELATE_SN_COL = "序列号"        # 第二个Excel中SN的列名（需与第一个Excel的SN格式一致）
RELATE_MODEL_COL = "设备型号"   # 第二个Excel中设备型号（model）的列名
RELATE_IP_COL = "管理地址"        # 第二个Excel中管理IP（ip）的列名
RELATE_DC_COL = "数据中心"      # 第二个Excel中数据中心（dc）的列名
RELATE_AREA_COL = "业务分区"


LLDP_FILENAME = DEFAULT_LLDP_FILENAME
LLDP_EXCEL_PATH = resource_path(os.path.join(EXCEL_DIR, LLDP_FILENAME))

LLDP_SHEET_NAME1 = "设备基础信息表"
LLDP_SHEET_NAME2 = "设备分区坐标表"
LLDP_SHEET_NAME3 = "设备分区互联表"

LLDP_NAME_COL = "设备名称"     # 第一个Excel中设备名称的列名
LLDP_AREA_COL = "所属分区"     # 第一个Excel中所属分区的列名
LLDP_DC_COL = "所属数据中心"
LLDP_VENDOR_COL = "所属厂商"
LLDP_SN_COL = "序列号SN"  
LLDP_MAC_COL = "MAC地址"
LLDP_TYPE_COL = "设备类型"
LLDP_MODEL_COL = "设备型号"
LLDP_IP_COL = "管理地址"
LLDP_X_COL = "topology_x"      # 第一个Excel中x坐标的列名
LLDP_Y_COL = "topology_y"      # 第一个Excel中y坐标的列名
LLDP_Global_COL = "是否在总拓扑体现"

# 业务规则配置
EXCLUDE_MODEL_PREFIX = ("CE-", "CEL", "CR")  # 排除的板卡型号前缀
RED_RGB_LIST = ["FF0000", "E60000", "F00000", "C00000"]  # 下架设备的红色RGB值

TARGET_SHEETS = ["设备清单"]  # 指定需要处理的Sheet名称（精准控制）
# 维保即将过保阈值：6个月
MAINTENANCE_WARNING_MONTHS = 6
# 维保统计：导出Excel指定列（需与Excel中实际列名匹配，若列名不同请修改）
EXPORT_COLUMNS = [
    "数据中心","业务分区","设备型号", "设备名称", "管理地址", "序列号", "维保开始", "维保结束"
]
# 维保统计：Excel下载文件名
EXPORT_FILENAME = f"设备维保统计_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"

# EOS即将停止阈值：2年
EOS_WARNING_MONTHS = 24

# EOS统计：导出Excel指定列（需与Excel中实际列名匹配，若列名不同请修改）
EOS_EXPORT_COLUMNS = [
    "数据中心","业务分区","设备型号", "设备名称", "管理地址", "序列号",  "EOS时间"
]
# EOS统计：Excel下载文件名
EOS_EXPORT_FILENAME = f"设备EOS统计_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"


# =========================== 新增：缓存策略配置（环境变量控制） ===========================
PRELOAD_ON_STARTUP = os.getenv('NETASSIST_PRELOAD', 'true').lower() == 'true'
USE_CACHE_AFTER_LOAD = os.getenv('NETASSIST_USE_CACHE', 'true').lower() == 'true'


# =========================== 新增：缓存管理器 ===========================
_DATA_CACHE = {}
_CACHE_LOADERS = {}

def register_loader(cache_key, loader_func):
    """注册一个数据加载器"""
    _CACHE_LOADERS[cache_key] = loader_func

def get_or_load_cache(cache_key, force_reload=False):
    """
    获取缓存数据，若不存在或强制刷新，则调用注册的加载器。
    若 USE_CACHE_AFTER_LOAD=False，则每次直接调用加载器，不缓存。
    """
    if not USE_CACHE_AFTER_LOAD:
        loader = _CACHE_LOADERS.get(cache_key)
        if loader:
            return loader()
        raise ValueError(f"未注册加载器: {cache_key}")

    if force_reload or cache_key not in _DATA_CACHE:
        loader = _CACHE_LOADERS.get(cache_key)
        if not loader:
            raise ValueError(f"未注册加载器: {cache_key}")
        _DATA_CACHE[cache_key] = loader()
    return _DATA_CACHE[cache_key]

def refresh_all_cache():
    """强制刷新所有缓存"""
    for key in list(_CACHE_LOADERS.keys()):
        get_or_load_cache(key, force_reload=True)

# ===== 分区拓扑缓存 =====
_ZONE_TOPOLOGY_CACHE = {}

def get_cached_zone_topology(zone_id):
    """获取分区拓扑数据，带缓存"""
    if not USE_CACHE_AFTER_LOAD:
        return _fetch_zone_topology_data(zone_id)
    if zone_id not in _ZONE_TOPOLOGY_CACHE:
        _ZONE_TOPOLOGY_CACHE[zone_id] = _fetch_zone_topology_data(zone_id)
    return _ZONE_TOPOLOGY_CACHE[zone_id]

def _fetch_zone_topology_data(zone_id):
    """获取指定分区的拓扑数据，带缓存和详细异常日志"""
    # ---------- 1. 获取并校验 zone_id ----------
    target_zone = zone_id
    if not target_zone:
        return {"success": False, "error": "缺少必要请求参数：zone_id", "status": 400}

    # ---------- 2. 读取 LLDP 生成的三个 sheet ----------
    try:
        # 设备基础信息表（包含从配置文件提取的 SN、MAC）
        base_lldp_df = pd.read_excel(LLDP_EXCEL_PATH, sheet_name=LLDP_SHEET_NAME1, dtype=str)
        # 设备分区坐标表（存储每个设备在各分区的坐标）
        coord_df = pd.read_excel(LLDP_EXCEL_PATH, sheet_name=LLDP_SHEET_NAME2, dtype=str)
        # 设备分区互联表（包含所有分区的链路）
        link_df = pd.read_excel(LLDP_EXCEL_PATH, sheet_name=LLDP_SHEET_NAME3, dtype=str)
    except FileNotFoundError:
        return {"success": False, "error": f"LLDP 数据文件不存在：{LLDP_EXCEL_PATH}", "status": 404}
    except Exception as e:
        return {"success": False, "error": f"读取 LLDP Excel 失败：{str(e)}", "status": 500}

    # ---------- 3. 校验各 sheet 的必要列 ----------
    # 基础信息表：至少需要设备名称列
    if LLDP_NAME_COL not in base_lldp_df.columns:
        return {"success": False, "error": f"基础信息表缺少「{LLDP_NAME_COL}」列", "status": 400}
    # 坐标表：需要设备名称、当前分区、x、y
    required_coord = ["设备名称", "当前分区", LLDP_X_COL, LLDP_Y_COL]
    for col in required_coord:
        if col not in coord_df.columns:
            return {"success": False, "error": f"坐标表缺少「{col}」列", "status": 400}
    # 互联表：需要所属分区、本端设备名称、本端接口、远端设备名称、远端接口
    required_link = ["所属分区", "本端设备名称", "本端设备接口", "远端设备名称", "远端设备接口"]
    for col in required_link:
        if col not in link_df.columns:
            return {"success": False, "error": f"互联表缺少「{col}」列", "status": 400}

    # ---------- 4. 筛选目标分区的数据 ----------
    # 4.1 检查 target_zone 是否存在于「所属分区」列
    zone_col_values = link_df["所属分区"].astype(str).str.strip()
    if target_zone.strip() not in set(zone_col_values.unique()):
        # 记录异常日志
        logging.error(f"[error] 请求的分区「{target_zone} 」不存在于互联表的「所属分区」列中,请补充后再试!")
        return {
            "success": False,
            "error": f"分区「{target_zone}」在互联表的「所属分区」列中不存在，请补充后再试！",
            "status": 404
        }

    # 4.2 互联表筛选
    link_df = link_df[zone_col_values == target_zone.strip()]
    if link_df.empty:
        return {
            "success": True,
            "nodes": [],
            "links": [],
            "zone_name": target_zone,
            "message": "该分区暂无互联数据"
        }

    # 4.2 收集所有出现在互联表中的设备名称
    device_names = set()
    for _, row in link_df.iterrows():
        local = str(row["本端设备名称"]).strip()
        remote = str(row["远端设备名称"]).strip()
        if local and local != "nan":
            device_names.add(local)
        if remote and remote != "nan":
            device_names.add(remote)

    # 4.3 筛选目标分区的坐标数据
    coord_df = coord_df[coord_df["当前分区"].astype(str).str.strip() == target_zone]
    coord_map = {}  # 设备名称 -> (x, y)
    for _, row in coord_df.iterrows():
        dev = str(row["设备名称"]).strip()
        if dev and dev != "nan":
            try:
                x = row[LLDP_X_COL] if pd.notna(row[LLDP_X_COL]) else None
            except:
                x = None

            try:
                y = row[LLDP_Y_COL] if pd.notna(row[LLDP_Y_COL]) else None
            except:
                y = None
            coord_map[dev] = (x, y)

    # ---------- 5. 建立 LLDP 基础信息映射（设备名称 -> SN、MAC）----------
    base_lldp_df = base_lldp_df.drop_duplicates(subset=[LLDP_NAME_COL], keep="first")
    base_lldp_df.set_index(LLDP_NAME_COL, inplace=True)
    lldp_info = {}
    for dev in device_names:
        if dev in base_lldp_df.index:
            row = base_lldp_df.loc[dev]
            lldp_info[dev] = {
                "sn": str(row.get(LLDP_SN_COL, "")) if pd.notna(row.get(LLDP_SN_COL)) else "",
                "mac": str(row.get(LLDP_MAC_COL, "")) if pd.notna(row.get(LLDP_MAC_COL)) else "",
                "area": str(row.get(LLDP_AREA_COL, "")) if pd.notna(row.get(LLDP_AREA_COL)) else "",
                "dc": str(row.get(LLDP_DC_COL, "")) if pd.notna(row.get(LLDP_DC_COL)) else "",
                "vendor": str(row.get(LLDP_VENDOR_COL, "")) if pd.notna(row.get(LLDP_VENDOR_COL)) else "",
                "model": str(row.get(LLDP_MODEL_COL, "")) if pd.notna(row.get(LLDP_MODEL_COL)) else "",
                "ip": str(row.get(LLDP_IP_COL, "")) if pd.notna(row.get(LLDP_IP_COL)) else "",
                "type": str(row.get(LLDP_TYPE_COL, "")) if pd.notna(row.get(LLDP_TYPE_COL)) else "",
            }
        else:
            lldp_info[dev] = {"sn": "", "mac": "", "area": "", "dc": "", "vendor": "", "model": "", "ip": "", "type": ""}

    # ---------- 6. 从设备清单（EXCEL_PATH）补充静态信息 ----------
    try:
        relate_df = pd.read_excel(EXCEL_PATH, sheet_name=RELATE_SHEET_NAME, dtype=str)
        # 去重并建立索引
        if RELATE_NAME_COL not in relate_df.columns:
            raise ValueError(f"设备清单缺少「{RELATE_NAME_COL}」列")
        relate_df = relate_df.drop_duplicates(subset=[RELATE_NAME_COL], keep="first")
        relate_df.set_index(RELATE_NAME_COL, inplace=True)
    except Exception as e:
        # 如果读取失败，则使用空映射（所有补充字段留空）
        relate_df = pd.DataFrame()
        logging.error(f"读取设备清单失败，将使用默认值：{str(e)}")

    # ---------- 7. 构建节点列表 ----------
    nodes = []
    for dev in device_names:
        # 基础字段
        node = {
            "id": dev,
            "name": dev,
            "sn": lldp_info[dev]["sn"],
            "mac": lldp_info[dev]["mac"],
            "area": lldp_info[dev]["area"],          # 从清单中获取业务分区（可选）
            "dc": lldp_info[dev]["dc"],
            "vendor": lldp_info[dev]["vendor"],
            "model": lldp_info[dev]["model"],
            "ip": lldp_info[dev]["ip"],
            "type": lldp_info[dev]["type"],
        }

        # 从设备清单补充信息
        if not relate_df.empty and dev in relate_df.index:
            row = relate_df.loc[dev]
            node.update({
                # "area": str(row.get(RELATE_AREA_COL, "")) if pd.notna(row.get(RELATE_AREA_COL)) else "",
                # "dc": str(row.get(RELATE_DC_COL, "")) if pd.notna(row.get(RELATE_DC_COL)) else "",
                # "vendor": str(row.get(RELATE_VENDOR_COL, "")) if pd.notna(row.get(RELATE_VENDOR_COL)) else "",
                # "model": str(row.get(RELATE_MODEL_COL, "")) if pd.notna(row.get(RELATE_MODEL_COL)) else "",
                # "ip": str(row.get(RELATE_IP_COL, "")) if pd.notna(row.get(RELATE_IP_COL)) else "",
            })

        # 添加坐标（优先从坐标表获取）
        x, y = coord_map.get(dev, (None, None))
        node["x"] = x
        node["y"] = y

        nodes.append(node)

    # ---------- 8. 构建链路列表（去重）----------
    links = []
    seen = set()
    for _, row in link_df.iterrows():
        local_dev = str(row["本端设备名称"]).strip()
        local_intf = str(row["本端设备接口"]).strip()
        remote_dev = str(row["远端设备名称"]).strip()
        remote_intf = str(row["远端设备接口"]).strip()

        if not local_dev or not remote_dev or local_dev == "nan" or remote_dev == "nan":
            continue

        # 生成唯一 ID（两端排序后拼接）
        conn1 = f"{local_dev}|{local_intf}"
        conn2 = f"{remote_dev}|{remote_intf}"
        sorted_conns = sorted([conn1, conn2])
        link_id = "|".join(sorted_conns)

        if link_id in seen:
            continue
        seen.add(link_id)

        links.append({
            "id": link_id,
            "source": local_dev,
            "target": remote_dev,
            "local_intf": local_intf,
            "remote_intf": remote_intf,
            "interface": f"{local_intf} ↔ {remote_intf}",
        })

    # ---------- 9. 返回结果 ----------
    return {
        "success": True,
        "nodes": nodes,
        "links": links,
        "zone_name": target_zone,
    }

# =========================================================================================

def copy_tree_skip_existing(src, dst):
    """
    递归复制 src 目录下的所有内容到 dst，若目标文件已存在则跳过。
    """
    if not os.path.exists(dst):
        os.makedirs(dst, exist_ok=True)
    for item in os.listdir(src):
        src_path = os.path.join(src, item)
        dst_path = os.path.join(dst, item)
        if os.path.isdir(src_path):
            copy_tree_skip_existing(src_path, dst_path)
        else:
            if not os.path.exists(dst_path):
                shutil.copy2(src_path, dst_path)
                print(f"[Info] 复制文件: {item}")

def ensure_resources_once():
    """
    仅首次运行时，将打包的资源复制到可写目录。
    使用标记文件防止重复复制。
    """
    if not getattr(sys, 'frozen', False):
        # 开发环境不复制，直接返回
        return

    # 标记文件放在 exe 所在目录
    flag_file = os.path.join(os.path.dirname(sys.executable), '.resources_copied')
    if os.path.exists(flag_file):
        print("[Info] 资源已复制过，跳过初始化。")
        return

    # 定义复制任务列表
    tasks = [
        # 任务格式: (源相对路径, 目标路径, 类型, 是否递归)
        # 1) 复制整个 asset_info 目录（递归所有子目录）
        # ('asset_info', app.config['ASSET_INFO_FOLDER'], 'dir', True),
        # ('templates_uploads', app.config['TEMPLATE_UPLOAD_FOLDER'], 'dir', True),
        ('data_uploads', app.config['DATA_UPLOAD_FOLDER'], 'dir', True),
        # 2) 复制单个文件（例如 data_uploads 下的一个示例文件）
        # ('data_uploads/示例数据.xlsx', os.path.join(app.config['DATA_UPLOAD_FOLDER'], '示例数据.xlsx'), 'file', False),
        (os.path.join(EXCEL_DIR, '设备维护清单_示例.xlsx'), os.path.join(app.config['ASSET_INFO_FOLDER'], '设备维护清单_示例.xlsx'), 'file', False),
        (os.path.join(EXCEL_DIR, '设备信息及互联表_示例.xlsx'), os.path.join(app.config['ASSET_INFO_FOLDER'], '设备信息及互联表_示例.xlsx'), 'file', False),
        (os.path.join(EXCEL_DIR, '设备名称映射表_示例.json'), os.path.join(app.config['ASSET_INFO_FOLDER'], '设备名称映射表_示例.json'), 'file', False),
        (os.path.join(TEMPLATE_EXT_DIR, '示例_CE6881-48S6CQ_MLAG_MEth带外_复用带外.txt'), os.path.join(app.config['TEMPLATE_UPLOAD_FOLDER'], '示例_CE6881-48S6CQ_MLAG_MEth带外_复用带外.txt'), 'file', False),
        (os.path.join(TEMPLATE_EXT_DIR, '示例_CE6881-48S6CQ_MLAG_业务口带外_独立心跳.txt'), os.path.join(app.config['TEMPLATE_UPLOAD_FOLDER'], '示例_CE6881-48S6CQ_MLAG_业务口带外_独立心跳.txt'), 'file', False),
        # 3) 复制目录但不递归（仅顶层文件）
        # ('templates_uploads', app.config['TEMPLATE_UPLOAD_FOLDER'], 'dir', False),
    ]

    for src_rel, dst_path, copy_type, recursive in tasks:
        src_full = os.path.join(sys._MEIPASS, src_rel)
        if not os.path.exists(src_full):
            print(f"[Warning] 源不存在: {src_full}")
            continue

        # 确保目标父目录存在
        dst_dir = os.path.dirname(dst_path) if copy_type == 'file' else dst_path
        os.makedirs(dst_dir, exist_ok=True)

        if copy_type == 'file':
            # 复制单个文件
            if not os.path.exists(dst_path):
                shutil.copy2(src_full, dst_path)
                print(f"[Info] 复制文件: {src_rel}")
        elif copy_type == 'dir':
            if recursive:
                # 递归复制整个目录树（跳过已存在的文件）
                copy_tree_skip_existing(src_full, dst_path)
            else:
                # 仅复制顶层文件（不进入子目录）
                for item in os.listdir(src_full):
                    src_item = os.path.join(src_full, item)
                    dst_item = os.path.join(dst_path, item)
                    if os.path.isfile(src_item) and not os.path.exists(dst_item):
                        shutil.copy2(src_item, dst_item)
                        print(f"[Info] 复制文件: {item} -> {dst_path}")
                # 忽略子目录

    # 创建标记文件，表示首次复制已完成
    with open(flag_file, 'w') as f:
        f.write('Resources copied at ' + str(datetime.now()))
    print("[Info] 首次资源复制完成。")

# 调用函数确保资源复制完成
ensure_resources_once()

# 加载配置文件设备清单及拓扑映射表.txt
def load_excel_config():
    """从 设备清单及拓扑映射表.txt 读取键值对配置（EXCEL_FILENAME=xxx, LLDP_FILENAME=yyy），文件不存在或变量缺失时使用默认值"""
    global EXCEL_FILENAME, LLDP_FILENAME, EXCEL_PATH, LLDP_EXCEL_PATH

    # 默认值
    new_excel = DEFAULT_EXCEL_FILENAME
    new_lldp = DEFAULT_LLDP_FILENAME

    # 读取配置文件（如果存在）
    if os.path.exists(GLOBAL_EXCEL_INFO_PATH):
        with open(GLOBAL_EXCEL_INFO_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip().upper()
                val = val.strip()
                if key == 'EXCEL_FILENAME':
                    new_excel = val
                elif key == 'LLDP_FILENAME':
                    new_lldp = val

    # 更新全局变量
    EXCEL_FILENAME = new_excel
    LLDP_FILENAME = new_lldp
    EXCEL_PATH = os.path.join(app.config['ASSET_INFO_FOLDER'], EXCEL_FILENAME)
    LLDP_EXCEL_PATH = os.path.join(app.config['ASSET_INFO_FOLDER'], LLDP_FILENAME)

    # 写回配置文件（统一格式）
    with open(GLOBAL_EXCEL_INFO_PATH, 'w', encoding='utf-8') as f:
        f.write(f"EXCEL_FILENAME={EXCEL_FILENAME}\nLLDP_FILENAME={LLDP_FILENAME}\n")

load_excel_config()

# 检查必要的Excel文件是否存在，不存在则提示并退出
def check_required_files():
    missing = []
    if not os.path.exists(EXCEL_PATH):
        missing.append(f"设备清单文件: {EXCEL_FILENAME}")
    else:
        print(f"[Info] 已完成设备清单文件加载: {EXCEL_FILENAME}")
    if not os.path.exists(LLDP_EXCEL_PATH):
        missing.append(f"LLDP数据文件: {LLDP_FILENAME}")
    else:
        print(f"[Info] 已完成LLDP数据文件加载: {LLDP_FILENAME}")



    if missing:
        print("\n" + "=" * 60)
        print("[错误] 缺少必要的Excel文件，无法启动应用！")
        print("=" * 60)
        print(f"请将以下文件放入目录: {app.config['ASSET_INFO_FOLDER']}")
        for m in missing:
            print(f"  - {m}")
        print(f"\n配置文件 {GLOBAL_EXCEL_INFO} 中指定的文件名可能与实际不符，")
        print("请确认文件名正确后，重新启动本程序。")
        print("=" * 60)
        input("按 Enter 键退出...")
        sys.exit(1)

check_required_files()


print("[Info] 应用初始化完成") 




# =====5、基础路由管理====

# 首页路由
@app.route('/')
# @login_required 
def index():
    print(f"=== 用户  访问首页 ===")  # 首页访问打印
    return render_template('index.html')


# base.html左侧菜单
@app.context_processor
def inject_menu():
    menu = [
        {
            'type': 'link',
            'label': '首页',
            'icon': 'fa-solid fa-house',
            'url': 'index',
            'endpoint': 'index'
        },
        {
            'type': 'link',
            'label': '信息图表',
            'icon': 'fa-solid fa-chart-column',
            'url': 'info_chart',
            'endpoint': 'info_chart'
        },
        {
            'type': 'dropdown',
            'label': '网络拓扑',
            'icon': 'fa-solid fa-hexagon-nodes',
            'children': [
                {'label': '网络总拓扑', 'url': 'topology_dc', 'endpoint': 'topology_dc', 'target': '_blank'},
                {'label': '网络分区拓扑', 'url': 'topology_zone', 'endpoint': 'topology_zone', 'target': '_blank'}
            ]
        },
        {
            'type': 'dropdown',
            'label': '批量脚本生成',
            'icon': 'fa-solid fa-code',
            'children': [
                {'label': '文件读取列表', 'url': 'template_file', 'endpoint': 'template_file'},
                {'label': '按场景生成', 'url': 'scene_batch', 'endpoint': 'scene_batch'},
            ]
        },

        {
            'type': 'link',
            'label': '文本排序对比',
            'icon': 'fa-solid fa-arrow-down-short-wide',
            'url': 'text_compare',
            'endpoint': 'text_compare',
            'target': '_blank'
        },
        {
            'type': 'link',
            'label': '关于',
            'icon': 'fa-solid fa-circle-info',
            'url': 'about',
            'endpoint': 'about'
        },
        # 其他菜单项按相同结构追加
    ]
    return {'menu': menu}


@app.context_processor
def inject_app_version():
    return {
        'app_name': APP_NAME,
        'app_version': VERSION,
        'app_version_text': version_text(),
    }


# index.html功能卡片
@app.context_processor
def inject_globals():
    cards = [
        {
            'title': '信息图表',
            'icon': 'fa-solid fa-chart-pie',
            'bg_color': 'bg-blue-100',
            'text_color': 'text-blue-600',
            'description': '主要用于查看网络设备的维保及数量的占比分布情况。',
            'url': 'info_chart',
            'url_text': '查看详情'
        },
        {
            'title': '网络总拓扑',
            'icon': 'fa-solid fa-hexagon-nodes',
            'bg_color': 'bg-red-100',
            'text_color': 'text-red-600',
            'description': '主要用于查看网络的总体架构。',
            'url': 'topology_dc',
            'url_text': '查看详情',
            'target': '_blank'
        },
        {
            'title': '批量脚本生成',
            'icon': 'fa-solid fa-code',
            'bg_color': 'bg-green-100',
            'text_color': 'text-green-600',
            'description': '可以使用不同场景工具批量生成变更脚本和回退脚本。',
            'url': 'scene_batch',
            'url_text': '查看详情'
        },
        {
            'title': '文本排序对比',
            'icon': 'fa-solid fa-arrow-down-short-wide',
            'bg_color': 'bg-orange-100',
            'text_color': 'text-yellow-600',
            'description': '支持排序后对比不同文本文件的结果。',
            'url': 'text_compare',
            'url_text': '查看详情',
            'target': '_blank'
        },
        # 未来新增卡片只需在这里添加即可
    ]
    return {'feature_cards': cards}

##### 监控大屏路由 #####

# ===================== 工具函数（通用能力） =====================
def fill_merged_cells(ws, df):
    """
    解析Excel合并单元格，填充合并区域的所有单元格值（解决合并单元格NaN问题）
    :param ws: openpyxl的Worksheet对象
    :param df: 原始DataFrame（pandas读取的Sheet数据）
    :return: 填充合并值后的DataFrame
    """
    # 复制DataFrame避免修改原数据
    df_filled = df.copy()
    
    # 遍历所有合并单元格区域
    for merged_range in ws.merged_cells.ranges:
        # 解析合并区域的行/列范围（openpyxl的行号从1开始，df索引从0开始）
        start_row = merged_range.min_row - 2  # 表头行是1，数据行从2开始 → df索引=行号-2
        end_row = merged_range.max_row - 2
        start_col = merged_range.min_col - 1  # 列号从1开始 → df列索引=列号-1
        end_col = merged_range.max_col - 1

        # 跳过表头行（若合并区域包含表头）
        if start_row < 0:
            start_row = 0

        # 确保行/列范围在df范围内
        if start_row >= len(df_filled) or start_col >= len(df_filled.columns):
            continue

        # 获取合并区域首个单元格的值（作为填充值）
        fill_value = df_filled.iloc[start_row, start_col]

        # 填充合并区域的所有单元格
        for row in range(start_row, end_row + 1):
            if row >= len(df_filled):
                break
            for col in range(start_col, end_col + 1):
                if col >= len(df_filled.columns):
                    break
                df_filled.iloc[row, col] = fill_value

    return df_filled

def get_red_bg_rows(excel_path, sheet_name, col_name):
    """
    获取指定Sheet中指定列的红色底色行号（含合并单元格，行号从2开始）
    :param excel_path: Excel文件路径
    :param sheet_name: 工作表名称
    :param col_name: 目标列名（如"设备型号"）
    :return: 红色底色行号列表（含合并区域所有行）
    """
    try:
        wb = load_workbook(excel_path, data_only=False)
        ws = wb[sheet_name]
        red_rows = []

        # 定位目标列的列号（数字，如A=1，B=2）
        target_col_idx = None
        for cell in ws[1]:  # 表头行（第1行）
            if cell.value == col_name:
                target_col_idx = cell.column
                break
        if not target_col_idx:
            wb.close()
            return red_rows

        # 第一步：收集所有非合并单元格的红色行
        normal_red_rows = []
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=target_col_idx)
            # 跳过合并单元格（避免重复处理）
            if cell.coordinate in ws.merged_cells:
                continue
            # 处理RGB对象，兼容新旧openpyxl版本
            rgb_value = cell.fill.fgColor.rgb
            if rgb_value:
                rgb_str = str(rgb_value) if not isinstance(rgb_value, str) else rgb_value
                rgb = rgb_str[2:] if len(rgb_str) >= 8 else rgb_str
                if rgb in RED_RGB_LIST:
                    normal_red_rows.append(row)

        # 第二步：处理合并单元格的红色行（合并区域全标记为红色）
        merged_red_rows = []
        for merged_range in ws.merged_cells.ranges:
            # 检查合并区域是否包含目标列
            if merged_range.min_col <= target_col_idx <= merged_range.max_col:
                # 获取合并区域首个单元格
                first_cell = ws.cell(row=merged_range.min_row, column=target_col_idx)
                # 检查首个单元格是否为红色
                rgb_value = first_cell.fill.fgColor.rgb
                if rgb_value:
                    rgb_str = str(rgb_value) if not isinstance(rgb_value, str) else rgb_value
                    rgb = rgb_str[2:] if len(rgb_str) >= 8 else rgb_str
                    if rgb in RED_RGB_LIST:
                        # 合并区域的所有行都标记为红色行
                        for row in range(merged_range.min_row, merged_range.max_row + 1):
                            if row >= 2:  # 仅统计数据行（跳过表头）
                                merged_red_rows.append(row)

        # 合并所有红色行，去重
        all_red_rows = list(set(normal_red_rows + merged_red_rows))
        wb.close()
        return all_red_rows
    except Exception as e:
        print(f"获取红色底色行失败：{e}")
        return []

def filter_valid_devices(raw_df, red_indexes):
    """
    独立的数据过滤函数（核心扩展入口）：排除下架设备（红色行）+ 排除板卡型号
    :param raw_df: 原始Sheet的DataFrame（包含所有列）
    :param red_indexes: 需要排除的红色行索引列表
    :return: 过滤后的完整DataFrame（包含所有列，可直接用于后续扩展分析）
    """
    # 步骤1：排除红色底色行（下架设备）
    df_filtered = raw_df.drop(red_indexes, axis=0).reset_index(drop=True)
    
    # 步骤2：排除板卡型号（CE-、CEL开头）
    df_filtered = df_filtered[
        ~df_filtered["设备型号"].astype(str).str.startswith(EXCLUDE_MODEL_PREFIX, na=False)
    ]
    
    # 步骤3：过滤空值（可选，根据业务需求）
    df_filtered = df_filtered.dropna(subset=["设备型号", "数据中心"])
    
    return df_filtered

# ===================== 业务统计函数（基于过滤后的数据） =====================

def stat_device_count():
    """
    统计有效设备数量（自动识别所有数据中心，兼容合并单元格，避免漏算）
    """
    # 动态统计字典，键为数据中心名称，值为设备数量
    dc_total = {}
    total_count = 0

    # 检查Excel文件是否存在
    if not os.path.exists(EXCEL_PATH):
        return {"error": f"Excel文件不存在：{EXCEL_PATH}"}, 404

    # 预加载工作簿（获取合并单元格信息）
    wb = load_workbook(EXCEL_PATH, data_only=False)

    # 遍历指定的Sheet（精准处理）
    for sheet in TARGET_SHEETS:
        try:
            # 跳过不存在的Sheet
            if sheet not in wb.sheetnames:
                logging.debug(f"Sheet[{sheet}]不存在，跳过")
                continue
            
            ws = wb[sheet]
            # 读取当前Sheet的原始数据
            raw_df = pd.read_excel(EXCEL_PATH, sheet_name=sheet)
            
            # 检查关键列是否存在
            required_cols = ["设备型号", "数据中心"]
            if not all(col in raw_df.columns for col in required_cols):
                logging.debug(f"Sheet[{sheet}]缺少关键列{required_cols}，跳过")
                continue
            
            # 核心修复1：填充合并单元格的值（消除NaN，避免漏统计）
            df_filled = fill_merged_cells(ws, raw_df)
            
            # 获取当前Sheet的红色行索引（含合并单元格）
            red_rows = get_red_bg_rows(EXCEL_PATH, sheet, "设备型号")
            red_indexes = [row - 2 for row in red_rows if (row - 2) >= 0 and (row - 2) < len(df_filled)]
            
            # 核心：调用独立过滤函数，获取干净数据
            valid_df = filter_valid_devices(df_filled, red_indexes)

            # 若有效数据为空，跳过统计
            if valid_df.empty:
                continue

            # 按数据中心分组统计，过滤掉数据中心为空或NaN的记录
            # 因为数据中心列可能包含空白，这里只统计非空有效值
            grouped = valid_df[valid_df["数据中心"].notna() & (valid_df["数据中心"] != "")] \
                               .groupby("数据中心", dropna=False)["设备型号"].count()
            
            # 累加到总字典
            for dc, cnt in grouped.items():
                dc_total[dc] = dc_total.get(dc, 0) + int(cnt)
        
        except Exception as e:
            logging.error(f"处理Sheet[{sheet}]失败：{e}")
            continue

    # 关闭工作簿
    wb.close()
    
    # 计算总数量
    total_count = int(sum(dc_total.values()))
    
    # 构建返回结果，包含total和各个数据中心的明细
    result = {"total": total_count}
    result.update(dc_total)   # 将各数据中心键值对展开
    # logging.info(result)
    return result

def stat_device_df():
    """
    统计有效设备dataframe（兼容合并单元格，避免漏算）
    """
    global_valid_df = pd.DataFrame()
    # 检查Excel文件是否存在
    if not os.path.exists(EXCEL_PATH):
        return {"error": f"Excel文件不存在：{EXCEL_PATH}"}, 404

    # 预加载工作簿（获取合并单元格信息）
    wb = load_workbook(EXCEL_PATH, data_only=False)

    # 遍历指定的Sheet（精准处理）
    for sheet in TARGET_SHEETS:
        # 跳过不存在的Sheet
        if sheet not in wb.sheetnames:
            logging.debug(f"Sheet[{sheet}]不存在，跳过")
            continue
        
        ws = wb[sheet]
        # 读取当前Sheet的原始数据
        raw_df = pd.read_excel(EXCEL_PATH, sheet_name=sheet)
        
        # 检查关键列是否存在
        required_cols = ["设备型号", "数据中心"]
        if not all(col in raw_df.columns for col in required_cols):
            logging.debug(f"Sheet[{sheet}]缺少关键列{required_cols}，跳过")
            continue
        
        # 核心修复1：填充合并单元格的值（消除NaN，避免漏统计）
        df_filled = fill_merged_cells(ws, raw_df)
        
        # 获取当前Sheet的红色行索引（含合并单元格）
        red_rows = get_red_bg_rows(EXCEL_PATH, sheet, "设备型号")
        red_indexes = [row - 2 for row in red_rows if (row - 2) >= 0 and (row - 2) < len(df_filled)]
        
        # 核心：调用独立过滤函数，获取干净数据
        valid_df = filter_valid_devices(df_filled, red_indexes)
                    
        # 基础合并（直接拼接，重置索引）
        global_valid_df = pd.concat(
            [global_valid_df, valid_df],
            ignore_index=True,  # 重置索引，避免重复索引
            sort=False  # 保留原有列顺序，列不一致时也能合并
        )
    
    # logging.debug(global_valid_df["数据中心"].unique(), global_valid_df["数据中心"].shape[0])

    # 关闭工作簿
    wb.close()
    
    return global_valid_df


# ===================== 扩展示例：基于过滤后的数据实现新需求 =====================
def stat_business_zone_ratio():
    """
    扩展示例1：统计各业务分区数量占比（复用过滤函数）
    """
    zone_count = {}
    total_valid = 0

    if not os.path.exists(EXCEL_PATH):
        return {"error": f"Excel文件不存在：{EXCEL_PATH}"}, 404

    for sheet in TARGET_SHEETS:
        try:
            raw_df = pd.read_excel(EXCEL_PATH, sheet_name=sheet)
            required_cols = ["设备型号", "数据中心", "业务分区"]  # 新增业务分区列
            if not all(col in raw_df.columns for col in required_cols):
                logging.debug(f"Sheet[{sheet}]缺少业务分区列，跳过")
                continue
            
            # 复用过滤函数，获取干净数据
            red_rows = get_red_bg_rows(EXCEL_PATH, sheet, "设备型号")
            red_indexes = [row - 2 for row in red_rows if row - 2 < len(raw_df)]
            valid_df = filter_valid_devices(raw_df, red_indexes)
            
            # 统计业务分区
            zone_group = valid_df.groupby("业务分区")["设备型号"].count()
            for zone, count in zone_group.items():
                zone_count[zone] = zone_count.get(zone, 0) + count
            total_valid += len(valid_df)
        
        except Exception as e:
            logging.error(f"统计业务分区失败：{e}")
            continue

    # 计算占比
    zone_ratio = {zone: (count/total_valid*100 if total_valid>0 else 0) for zone, count in zone_count.items()}
    return {
        "total_valid_devices": total_valid,
        "business_zone_count": zone_count,
        "business_zone_ratio": zone_ratio  # 百分比
    }

def check_maintenance_expired():
    """
    统计设备维保状态（无维保信息/已过保/未过保/即将过保（半年内））
    返回格式适配前端：{success: bool, total: 总数, data: [{name: 状态, value: 数量}], 详细设备列表}
    """
    # 初始化状态统计
    status_count = {
        "无维保信息": 0,
        "已过保": 0,
        "未过保": 0,
        "即将过保": 0
    }
    total_valid_devices = 0  # 有效设备总数（排除下架/板卡后）
    # 初始化详细设备列表
    device_detail = {
        "无维保信息": [],
        "已过保": [],
        "未过保": [],
        "即将过保": []
    }

    # 检查Excel文件是否存在
    if not os.path.exists(EXCEL_PATH):
        return {
            "success": False,
            "error": f"Excel文件不存在：{EXCEL_PATH}",
            "total": 0,
            "data": []
        }

    # 预加载工作簿（处理合并单元格）
    wb = load_workbook(EXCEL_PATH, data_only=False)
    current_time = datetime.now()  # 当前时间
    # logging.debug(f"当前时间：{current_time}")
    # 计算即将过保阈值：当前时间 + 6个月
    warning_threshold = current_time + relativedelta(months=MAINTENANCE_WARNING_MONTHS)
    # logging.debug(f"即将过保阈值：{warning_threshold}")
    # 遍历指定Sheet
    for sheet in TARGET_SHEETS:
        try:
            if sheet not in wb.sheetnames:
                logging.debug(f"Sheet[{sheet}]不存在，跳过")
                continue
            ws = wb[sheet]
            # 读取原始数据
            raw_df = pd.read_excel(EXCEL_PATH, sheet_name=sheet)
            # 检查关键列
            required_cols = ["设备型号", "数据中心", "维保结束"]
            if not all(col in raw_df.columns for col in required_cols):
                logging.debug(f"Sheet[{sheet}]缺少关键列{required_cols}，跳过")
                continue

            # 步骤1：填充合并单元格值（避免NaN漏算）
            df_filled = fill_merged_cells(ws, raw_df)  # 复用之前的合并单元格填充函数

            # 步骤2：过滤下架设备（红色行）+ 板卡型号
            red_rows = get_red_bg_rows(EXCEL_PATH, sheet, "设备型号")  # 复用之前的红色行函数
            red_indexes = [row - 2 for row in red_rows if (row - 2) >= 0 and (row - 2) < len(df_filled)]
            valid_df = filter_valid_devices(df_filled, red_indexes)  # 复用过滤函数
            total_valid_devices += len(valid_df)

            # 步骤3：处理维保时间，统计状态
            # 转换维保结束为datetime（错误值转为NaT）
            valid_df["维保结束_转换"] = pd.to_datetime(valid_df["维保结束"], errors="coerce")

            for idx, row in valid_df.iterrows():
                device_info = {
                    "设备型号": row["设备型号"],
                    "数据中心": row["数据中心"],
                    "维保结束": row["维保结束"] if pd.notna(row["维保结束"]) else "无"
                }
                expire_time = row["维保结束_转换"]

                # 状态判断逻辑
                if pd.isna(expire_time):
                    # 无维保信息
                    status_count["无维保信息"] += 1
                    device_detail["无维保信息"].append(device_info)
                else:
                    # expire_time = expire_time.to_pydatetime()  # 转为Python datetime
                    if expire_time < current_time:
                        # 已过保
                        status_count["已过保"] += 1
                        device_detail["已过保"].append(device_info)
                    elif current_time <= expire_time <= warning_threshold:
                        # 即将过保（半年内）
                        status_count["即将过保"] += 1
                        device_detail["即将过保"].append(device_info)
                    else:
                        # 未过保（超过半年）
                        status_count["未过保"] += 1
                        device_detail["未过保"].append(device_info)

        except Exception as e:
            logging.error(f"处理Sheet[{sheet}]维保数据失败：{e}")
            continue

    wb.close()

    # 转换为前端需要的格式（严格按图例顺序：无维保、已过保、未过保、即将过保）
    chart_data = [
        {"name": "无维保信息", "value": int(status_count["无维保信息"])},
        {"name": "已过保", "value": int(status_count["已过保"])},
        {"name": "未过保", "value": int(status_count["未过保"])},
        {"name": "即将过保", "value": int(status_count["即将过保"])}
    ]

    # 返回最终结果（兼容前端success字段）
    return {
        "success": True,
        "total": int(total_valid_devices),  # 总有效设备数
        "data": chart_data,  # 图表数据
        "device_detail": device_detail  # 详细设备列表（可选，前端可按需使用）
    }

def get_maintenance_device_detail():
    """
    获取各维保状态的设备明细（复用过滤逻辑，返回分类数据）
    :return: 按状态分类的设备明细字典
    """
    device_detail = {
        "已过保": [],
        "即将过保": [],
        "无维保信息": [],
        "未过保": []
    }
    if not os.path.exists(EXCEL_PATH):
        return {"error": f"Excel文件不存在：{EXCEL_PATH}"}

    # 预加载工作簿（处理合并单元格）
    wb = load_workbook(EXCEL_PATH, data_only=False)
    current_time = datetime.now()
    warning_threshold = current_time + relativedelta(months=MAINTENANCE_WARNING_MONTHS)

    # 遍历指定Sheet
    for sheet in TARGET_SHEETS:
        try:
            if sheet not in wb.sheetnames:
                logging.debug(f"Sheet[{sheet}]不存在，跳过")
                continue
            ws = wb[sheet]
            # 读取原始数据
            raw_df = pd.read_excel(EXCEL_PATH, sheet_name=sheet)
            # 检查导出所需列是否存在（缺失列填充空值）
            for col in EXPORT_COLUMNS:
                if col not in raw_df.columns:
                    raw_df[col] = ""  # 缺失列填充空值

            # 步骤1：填充合并单元格值
            df_filled = fill_merged_cells(ws, raw_df)

            # 步骤2：过滤下架设备（红色行）+ 板卡型号
            red_rows = get_red_bg_rows(EXCEL_PATH, sheet, "设备型号")
            red_indexes = [row - 2 for row in red_rows if (row - 2) >= 0 and (row - 2) < len(df_filled)]
            valid_df = filter_valid_devices(df_filled, red_indexes)

            # 步骤3：处理维保时间，分类设备
            valid_df["维保结束_转换"] = pd.to_datetime(valid_df["维保结束"], errors="coerce")
            valid_df["维保开始_转换"] = pd.to_datetime(valid_df["维保开始"], errors="coerce")

            for idx, row in valid_df.iterrows():
                # 提取导出列数据
                device_info = {
                    "数据中心": row["数据中心"],
                    "业务分区": row["业务分区"],
                    "设备型号": row["设备型号"],
                    "设备名称": row["设备名称"],
                    "管理地址": row["管理地址"],
                    "序列号": row["序列号"],
                    "维保开始": row["维保开始"] if pd.notna(row["维保开始"]) else "",
                    "维保结束": row["维保结束"] if pd.notna(row["维保结束"]) else ""
                }
                expire_time = row["维保结束_转换"]

                # 状态判断
                if pd.isna(expire_time):
                    device_detail["无维保信息"].append(device_info)
                else:
                    expire_time = expire_time.to_pydatetime()
                    if expire_time < current_time:
                        device_detail["已过保"].append(device_info)
                    elif current_time <= expire_time <= warning_threshold:
                        device_detail["即将过保"].append(device_info)
                    else:
                        device_detail["未过保"].append(device_info)

        except Exception as e:
            logging.error(f"处理Sheet[{sheet}]导出数据失败：{e}")
            continue

    wb.close()
    return device_detail

# 优化后的format_excel_in_memory函数
def format_excel_in_memory(excel_bytes: BytesIO) -> BytesIO:
    """
    统一格式化Excel文件
    核心优化：
    1. 日期列识别：关键词匹配，格式转为yyyy/mm/dd，去时分秒，中文内容（如未发布）忽略
    2. 所有单元格水平+垂直居中，列宽自适应内容
    :param excel_bytes: 内存中的Excel字节流
    :return: 格式化后的Excel字节流
    """
    # 1. 初始化配置
    excel_bytes.seek(0)
    wb = load_workbook(excel_bytes)
    # 日期列关键词（中英文兼容）
    date_column_keywords = ["时间", "维保", "开始", "结束", "eos"]
    # 中文内容匹配正则（用于跳过非日期类中文）
    chinese_pattern = re.compile(r'[\u4e00-\u9fa5]+')
    # 目标日期格式
    target_date_format = 'yyyy/mm/dd'

    # 2. 遍历所有sheet处理
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        
        # 2.1 第一步：识别日期列（按列名关键词匹配）
        date_columns = []
        for col_num in range(1, ws.max_column + 1):
            col_letter = get_column_letter(col_num)
            # 列名转小写，便于匹配
            col_name = str(ws[f"{col_letter}1"].value or "").lower().strip()
            if any(keyword in col_name for keyword in date_column_keywords):
                date_columns.append(col_letter)
        
        # 2.2 第二步：处理所有单元格（居中+日期格式）
        for row in range(1, ws.max_row + 1):
            for col_num in range(1, ws.max_column + 1):
                col_letter = get_column_letter(col_num)
                cell = ws[f"{col_letter}{row}"]
                
                # 所有单元格强制水平+垂直居中
                cell.alignment = Alignment(
                    horizontal='center',
                    vertical='center',
                    wrap_text=False  # 可选：是否自动换行，根据需求调整
                )
                
                # 日期列特殊处理（跳过表头行+中文内容）
                if row > 1 and col_letter in date_columns:
                    cell_value = cell.value
                    # 跳过空值/中文内容（如未发布、无EOS信息等）
                    if cell_value is None or chinese_pattern.search(str(cell_value)):
                        continue
                    
                    # 处理日期格式，强制去掉时分秒
                    try:
                        # 情况1：单元格值是datetime类型
                        if isinstance(cell_value, datetime):
                            # 截断时分秒，仅保留日期
                            cell.value = cell_value.date()
                            cell.number_format = target_date_format
                        # 情况2：单元格值是字符串类型的日期（如2025-12-16 12:00:00）
                        elif isinstance(cell_value, str):
                            # 尝试解析为日期，失败则跳过
                            parsed_date = pd.to_datetime(cell_value, format="mixed", errors="raise")
                            cell.value = parsed_date.date()
                            cell.number_format = target_date_format
                    except (ValueError, TypeError):
                        # 解析失败（非日期格式），跳过
                        continue
        
        # 2.3 第三步：列宽自适应（精准计算最大内容长度）
        for col_num in range(1, ws.max_column + 1):
            col_letter = get_column_letter(col_num)
            max_length = 0
            # 遍历该列所有单元格，计算最大内容长度
            for row in range(1, ws.max_row + 1):
                cell_value = str(ws[f"{col_letter}{row}"].value or "").strip()
                # 中文占2个字符宽度，英文/数字占1个，精准计算显示宽度
                str_length = len(cell_value.encode('gbk')) if chinese_pattern.search(cell_value) else len(cell_value)
                if str_length > max_length:
                    max_length = str_length
            # 列宽自适应（+2留边距，最大50避免过宽）
            ws.column_dimensions[col_letter].width = min(max_length + 2, 50)

    # 3. 保存并返回格式化后的Excel
    output = BytesIO()
    wb.save(output)
    wb.close()
    output.seek(0)
    return output

def get_eos_detail():
    """
    获取各EOS状态的设备明细数据（修复EOS时间列填充逻辑）
    返回格式：{
        "服务中": dataframe,
        "即将停止": dataframe,
        "服务停止": dataframe,
        "无EOS信息": dataframe
    }
    """
    try:
        # 1. 校验Excel文件是否存在
        if not os.path.exists(EXCEL_PATH):
            return {"error": f"Excel文件不存在：{EXCEL_PATH}"}
        
        # 2. 读取Excel的EOS时间参考表，构建「型号-EOS时间」映射字典
        excel_eos_df = pd.read_excel(
            EXCEL_PATH, 
            sheet_name="设备EOS信息", 
            engine="openpyxl",
            usecols=["设备型号", "设备EOS时间"]
        )
        
        # 校验Excel必要列
        required_cols = ["设备型号", "设备EOS时间"]
        if not all(col in excel_eos_df.columns for col in required_cols):
            return {"error": f"Excel缺少必要列（需包含{required_cols}）"}
        if excel_eos_df.empty:
            return {"error": "Excel的EOS时间参考表无数据"}
        
        # 3. 清洗Excel数据，构建型号到EOS时间的映射字典
        excel_eos_df["设备型号"] = excel_eos_df["设备型号"].astype(str).str.strip()
        # 保留原始EOS时间字符串（不解析，方便直接填充）
        eos_mapping = excel_eos_df.drop_duplicates(subset=["设备型号"]).set_index("设备型号")["设备EOS时间"].to_dict()
        
        # 4. 获取有效设备数据
        global_valid_df = stat_device_df()
        if not isinstance(global_valid_df, pd.DataFrame) or global_valid_df.empty:
            return {"error": "global_valid_df非有效DataFrame/无设备数据"}
        if "设备型号" not in global_valid_df.columns:
            return {"error": "global_valid_df缺少「设备型号」列"}
        
        # 5. 初始化各状态数据框（使用指定导出列）
        status_dfs = {
            "服务中": pd.DataFrame(columns=EOS_EXPORT_COLUMNS),
            "即将停止": pd.DataFrame(columns=EOS_EXPORT_COLUMNS),
            "服务停止": pd.DataFrame(columns=EOS_EXPORT_COLUMNS),
            "无EOS信息": pd.DataFrame(columns=EOS_EXPORT_COLUMNS)
        }
        
        # 6. 准备时间参数（使用24个月阈值）
        today = datetime.now()
        warn_date = today + relativedelta(months=EOS_WARNING_MONTHS)
        
        # 7. 清洗设备型号
        device_df = global_valid_df.copy()
        device_df["设备型号"] = device_df["设备型号"].astype(str).str.strip()
        device_df = device_df[device_df["设备型号"] != ""]
        
        # 8. 筛选符合导出列要求的数据（确保列顺序与配置一致）
        export_df = device_df.reindex(columns=EOS_EXPORT_COLUMNS).copy()
        
        # 9. 逐行判断状态并分类 + 填充EOS时间列
        for idx, device_row in export_df.iterrows():
            device_model = str(device_row["设备型号"]).strip()
            # 初始化EOS时间为默认值
            eos_time_fill = "无EOS信息"
            device_row["EOS时间"] = eos_time_fill  # 先默认填充
            
            # 处理型号不在映射中的情况
            if device_model not in eos_mapping:
                status_dfs["无EOS信息"] = pd.concat([status_dfs["无EOS信息"], device_row.to_frame().T], ignore_index=True)
                continue
            
            # 获取Excel中的原始EOS时间字符串
            eos_time_str = eos_mapping[device_model]
            # 填充EOS时间列（使用原始字符串，不解析）
            device_row["EOS时间"] = eos_time_str if pd.notna(eos_time_str) else "EOS时间为空"
            
            # 处理"未发布"场景
            if isinstance(eos_time_str, str) and eos_time_str.strip() == "未发布":
                status_dfs["服务中"] = pd.concat([status_dfs["服务中"], device_row.to_frame().T], ignore_index=True)
                continue
            
            # 解析EOS时间（仅用于判断状态，不影响填充）
            try:
                eos_date = pd.to_datetime(eos_time_str, format="mixed", errors="raise")
            except (ValueError, TypeError):
                device_row["EOS时间"] = "EOS时间解析失败"  # 标记解析失败
                status_dfs["无EOS信息"] = pd.concat([status_dfs["无EOS信息"], device_row.to_frame().T], ignore_index=True)
                continue
            
            # 按时间区间判断状态
            eos_date = eos_date.to_pydatetime()
            if eos_date > warn_date:
                status_dfs["服务中"] = pd.concat([status_dfs["服务中"], device_row.to_frame().T], ignore_index=True)
            elif today <= eos_date <= warn_date:
                status_dfs["即将停止"] = pd.concat([status_dfs["即将停止"], device_row.to_frame().T], ignore_index=True)
            elif eos_date < today:
                status_dfs["服务停止"] = pd.concat([status_dfs["服务停止"], device_row.to_frame().T], ignore_index=True)
        
        return status_dfs
        
    except Exception as e:
        return {"error": f"获取EOS明细数据失败：{str(e)}"}

def check_manufacturer_status():
    """读取Excel，统计各厂商设备数量（自动适配厂商数量）"""

    if not os.path.exists(EXCEL_PATH):
        return {"error": f"Excel文件不存在：{EXCEL_PATH}"}
    
    # 读取所有sheet，自动适配任意sheet数量
    excel_data = pd.read_excel(EXCEL_PATH, sheet_name="其他厂商设备数量", engine="openpyxl")
    
    manufacturer_data = {}
    # 自动合并同厂商数据
    if "厂商" not in excel_data.columns or "数量" not in excel_data.columns:
        return {"error": f"Excel文件'厂商'或'数量'列不存在：{EXCEL_PATH}"}
    
    # 数据清洗：自动处理空值、非数值
    df = excel_data.dropna(subset=["厂商", "数量"])
    df["数量"] = pd.to_numeric(df["数量"], errors="coerce").fillna(0)
    
    # 按厂商分组求和，自动适配任意厂商数量
    sheet_manufacturer = df.groupby("厂商")["数量"].sum().to_dict()
    for manufacturer, count in sheet_manufacturer.items():
        manufacturer_data[manufacturer] = manufacturer_data.get(manufacturer, 0) + count
    
    if not manufacturer_data:
        return {"error": "未找到有效厂商数据"}
    
    # 自动生成前端可直接使用的格式，无需前端二次处理
    result_list = [
        {"manufacturer": k, "total_count": int(v)} 
        for k, v in manufacturer_data.items()
    ] if manufacturer_data else []  # 空数据时返回[]
    
    # 返回：明细数据+自动统计的总数+汇总值（前端直接用）
    return {
        "data": result_list,  # 所有厂商的明细（数量自动适配）
        "total_manufacturer": len(result_list),  # 厂商总数（自动计算）
        "total_device": sum([item["total_count"] for item in result_list])  # 设备总数（自动计算）
    }

def filter_device_model():
    """根据过滤后的设备清单，返回所有设备型号（去重）"""
    
    global_valid_df = stat_device_df()
    # 去重并转为列表（确保返回可序列化的普通列表）
    filter_devices_model = sorted(global_valid_df["设备型号"].unique().tolist())
    
    return filter_devices_model

def filter_fenqu():
    """根据过滤后的设备清单，返回所有业务分区（去重）"""
    
    global_valid_df = stat_device_df()
    # 去重并转为列表（确保返回可序列化的普通列表）
    filter_fenqu = sorted(global_valid_df["业务分区"].unique().tolist())
    
    return filter_fenqu


# ===================== 接口定义 =====================

@app.route("/dc_status", methods=["GET"])
def dc_status():
    """核心接口：返回各数据中心设备数量统计（从缓存读取）"""
    try:
        data = get_or_load_cache('dc_status')
        if "error" in data:
            return jsonify(data), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/maintenance_status", methods=["GET"])
def maintenance_status():
    """扩展接口2：返回设备维保过保状态"""
    try:
        data = get_or_load_cache('maintenance_status')
        if "error" in data:
            return jsonify(data), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/export_maintenance_excel", methods=["GET"])
def export_maintenance_excel():
    """
    导出维保统计Excel接口：4个Sheet（已过保/即将过保/无维保信息/未过保）
    """
    try:
        # 获取分类设备明细
        device_detail = get_maintenance_device_detail()
        if "error" in device_detail:
            return jsonify({"success": False, "error": device_detail["error"]}), 404

        # 内存中创建Excel文件（避免生成临时文件）
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            # 遍历4个状态，分别写入Sheet
            for status in ["已过保", "即将过保", "无维保信息", "未过保"]:
                # 转换为DataFrame（空数据时生成空DF）
                df = pd.DataFrame(device_detail[status]) if device_detail[status] else pd.DataFrame(columns=EXPORT_COLUMNS)
                # 写入Sheet，设置列宽（优化显示）
                df.to_excel(writer, sheet_name=status, index=False)

        # 重置文件指针到开头（否则send_file会读取空内容）
        output.seek(0)
        # 第二步：格式化内存中的Excel（居中、自适应列宽、时间转date）
        formatted_output = format_excel_in_memory(output)
        
        # 设置响应头，触发下载
        return send_file(
            formatted_output,
            as_attachment=True,
            download_name=EXPORT_FILENAME,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        logging.error(f"导出Excel失败：{e}")
        return jsonify({"success": False, "error": f"导出失败：{str(e)}"}), 500

@app.route("/export_eos_excel", methods=["GET"])
def export_eos_excel():
    """导出EOS明细数据到Excel（严格复用原始format_excel_in_memory函数）"""
    try:
        # 1. 获取EOS明细数据
        eos_details = get_eos_detail()
        
        # 2. 错误处理
        if isinstance(eos_details, dict) and "error" in eos_details:
            flash(eos_details["error"], "danger")
            return redirect(url_for('index'))
        
        # 3. 第一步：将数据写入内存Excel（未格式化）
        raw_excel = BytesIO()
        with pd.ExcelWriter(raw_excel, engine='openpyxl') as writer:
            for status, df in eos_details.items():
                # 替换sheet名称中的特殊字符，限制长度
                safe_sheet_name = status.replace('/', '_').replace('\\', '_')[:31]
                df.to_excel(writer, sheet_name=safe_sheet_name, index=False)
        # 关键：关闭writer后重置指针
        raw_excel.seek(0)
        
        # 4. 第二步：复用原始format_excel_in_memory函数格式化Excel
        formatted_excel = format_excel_in_memory(raw_excel)
        
        # 5. 准备文件下载
        filename = EOS_EXPORT_FILENAME
        
        return send_file(
            formatted_excel,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        flash(f"导出EOS Excel失败：{str(e)}", "danger")
        return redirect(url_for('index'))
 

@app.route("/manufacturer_status", methods=["GET"])
def manufacturer_status():
    """扩展接口2：返回不同厂商设备数量"""
    try:
        data = get_or_load_cache('manufacturer_status')
        if "error" in data:
            return jsonify(data), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----- 将原来的 eos_status 计算函数重命名 -----
def _eos_status_compute():
    """
    统计设备EOS状态（服务停止/即将停止/服务中/无EOS信息）
    核心逻辑：
    1. 以global_valid_df（每行1台设备）为计数依据；
    2. Excel的「设备EOS信息」仅提供各型号的EOS时间参考；
    3. 即将停止阈值：当前时间+2年；
    4. 无EOS信息：型号不在Excel表中 / EOS时间为空/解析失败 / 未找到匹配型号。
    """
    try:
        # 1. 校验Excel文件是否存在
        if not os.path.exists(EXCEL_PATH):
            return {"error": f"Excel文件不存在：{EXCEL_PATH}"}
        
        # 2. 读取Excel的EOS时间参考表，构建「型号-EOS时间」映射字典
        excel_eos_df = pd.read_excel(
            EXCEL_PATH, 
            sheet_name="设备EOS信息", 
            engine="openpyxl",
            usecols=["设备型号", "设备EOS时间"]
        )
        
        # 校验Excel必要列
        required_cols = ["设备型号", "设备EOS时间"]
        if not all(col in excel_eos_df.columns for col in required_cols):
            logging.debug(f"Excel缺少必要列（需包含{required_cols}）")
            return {"error": "Excel缺少必要列"}
        if excel_eos_df.empty:
            logging.debug("Excel的EOS时间参考表无数据")
            return {"error": "Excel的EOS时间参考表无数据"}
        
        # 3. 清洗Excel数据，构建型号到EOS时间的映射字典（去重+去空格）
        excel_eos_df["设备型号"] = excel_eos_df["设备型号"].astype(str).str.strip()
        # 去重（保留第一个匹配的EOS时间）
        eos_mapping = excel_eos_df.drop_duplicates(subset=["设备型号"]).set_index("设备型号")["设备EOS时间"].to_dict()
        
        # 4. 初始化状态统计
        eos_stats = {
            "服务停止": 0,
            "即将停止": 0,
            "无EOS信息": 0,
            "服务中": 0,
        }
        today = datetime.now()
        warn_date = today + relativedelta(years=2)  # 精准2年，自动处理闰年

        global_valid_df = stat_device_df()
        if not isinstance(global_valid_df, pd.DataFrame) or global_valid_df.empty:
            logging.debug("global_valid_df非有效DataFrame/无设备数据")
            return {"error": "无有效设备数据"}
        if "设备型号" not in global_valid_df.columns:
            logging.debug("global_valid_df缺少「设备型号」列")
            return {"error": "global_valid_df缺少「设备型号」列"}
        
        device_df = global_valid_df.copy()
        device_df["设备型号"] = device_df["设备型号"].astype(str).str.strip()
        device_df = device_df[device_df["设备型号"] != ""]

        for _, device_row in device_df.iterrows():
            device_model = device_row["设备型号"]
            if device_model not in eos_mapping:
                eos_stats["无EOS信息"] += 1
                continue
            
            eos_time_str = eos_mapping[device_model]
            if isinstance(eos_time_str, str) and eos_time_str.strip() == "未发布":
                eos_stats["服务中"] += 1
                continue
            
            try:
                eos_date = pd.to_datetime(eos_time_str, format="mixed", errors="raise")
            except (ValueError, TypeError):
                eos_stats["无EOS信息"] += 1
                continue
            
            eos_date = eos_date.to_pydatetime()
            if eos_date > warn_date:
                eos_stats["服务中"] += 1
            elif today <= eos_date <= warn_date:
                eos_stats["即将停止"] += 1
            elif eos_date < today:
                eos_stats["服务停止"] += 1

        eos_data = [
            {"status": status, "count": int(count)} 
            for status, count in eos_stats.items()
        ]
        total_device = sum([item["count"] for item in eos_data])
        total_status = len(eos_data)

        return {
            "code": 200,
            "msg": "success",
            "data": eos_data,
            "total_device": total_device,
            "total_status": total_status
        }

    except Exception as e:
        return {"error": f"EOS状态统计失败：{str(e)}，错误类型：{type(e).__name__}"}


# ----- 修改路由，使用缓存 -----
@app.route("/eos_status", methods=["GET"])
def eos_status():
    try:
        data = get_or_load_cache('eos_status')
        if isinstance(data, dict) and "error" in data:
            return jsonify(data), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/filter_device_model_count", methods=["GET"])
def filter_device_model_count():
    """
    根据过滤后的设备清单，统计各型号及对应数量
    支持按选中的型号列表进行过滤
    """
    try:
        # 从缓存获取全量数据
        full_cache = get_or_load_cache('device_model_count')
        if "error" in full_cache:
            return jsonify(full_cache), 503

        selected_models = request.args.getlist('models')
        full_data = full_cache["data"]  # dict

        if selected_models and selected_models[0]:
            filtered_data = {k: v for k, v in full_data.items() if k in selected_models}
        else:
            filtered_data = full_data

        return jsonify({
            "code": 200,
            "msg": "success",
            "data": filtered_data,
            "total": sum(filtered_data.values())
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/filter_fenqu_count", methods=["GET"])
def filter_fenqu_count():
    """
    根据过滤后的设备清单，统计各业务分区及对应数量
    支持按选中的业务分区列表进行过滤
    """
    try:
        full_cache = get_or_load_cache('business_zone_count')
        if "error" in full_cache:
            return jsonify(full_cache), 503

        selected_fenqu = request.args.getlist('fenqu')
        full_data = full_cache["data"]

        if selected_fenqu and selected_fenqu[0]:
            filtered_data = {k: v for k, v in full_data.items() if k in selected_fenqu}
        else:
            filtered_data = full_data

        return jsonify({
            "code": 200,
            "msg": "success",
            "data": filtered_data,
            "total": sum(filtered_data.values())
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# 加载信息图表页面----------------
@app.route('/info_chart')
def info_chart():
    print(f"=== 用户  访问信息图表页面 ===")
    return render_template('info_chart.html')

@app.route('/api/device_models')
def api_device_models():
    """返回去重后的设备型号列表（纯数组）"""
    try:
        data = get_or_load_cache('device_model_list')
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/business_zones')
def api_business_zones():
    """返回去重后的业务分区列表（纯数组）"""
    try:
        data = get_or_load_cache('business_zone_list')
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== 缓存键显示名称映射（仅用于日志输出） =====
CACHE_DISPLAY_NAMES = {
    'dc_status': '数据中心设备统计',
    'maintenance_status': '设备维保状态统计',
    'eos_status': '设备EOS状态统计',
    'manufacturer_status': '厂商设备数量统计',
    'device_model_list': '设备型号列表',
    'business_zone_list': '业务分区列表',
    'device_model_count': '设备型号数量统计',
    'business_zone_count': '业务分区数量统计',
    'dc_topology_data': '总拓扑数据',
    'zone_topology_data': '分区拓扑数据',
}

def get_cache_display_name(key):
    """返回缓存键对应的显示名称，若无映射则返回原键"""
    return CACHE_DISPLAY_NAMES.get(key, key)

# ===================== 新增：刷新缓存接口 =====================
@app.route("/refresh_cache", methods=["POST"])
def refresh_cache():
    try:
        data = request.get_json() or {}
        keys = data.get('keys')
        if keys and isinstance(keys, list) and len(keys) > 0:
            for key in keys:
                if key == 'zone_topology_data':
                    # 清空分区拓扑缓存
                    _ZONE_TOPOLOGY_CACHE.clear()
                    logging.info("[缓存] 分区拓扑缓存已清空")
                elif key in _CACHE_LOADERS:
                    _DATA_CACHE[key] = _CACHE_LOADERS[key]()
                    logging.info(f"[缓存] {key} 已刷新")
                else:
                    logging.warning(f"缓存键 {key} 未注册或未处理，跳过")
            message = f"已刷新指定的缓存键: {', '.join(keys)}"
            print(f"[缓存] {get_cache_display_name(key)} 已重新加载完成")
        else:
            # refresh_all_cache()
            message = "缓存键为空，请指定要刷新的键存列表"
        return jsonify({"success": True, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500




##### 关于说明路由 #####

# 加载关于说明页面----------------
@app.route('/about')
def about():
    print(f"=== 用户  访问关于页 ===")
    return render_template('about.html')



##### 拓扑管理路由 #####
# 构建sn映射字典
def build_sn_relate_map() -> Dict[str, Dict[str, str]]:
    """
    构建设备SN到（model、ip、dc）的映射字典
    返回：key=设备SN（字符串），value=包含model、ip、dc的字典
    若 Excel 文件不存在或读取失败，返回空字典并打印错误。
    """
    sn_relate_map = {}
    try:
        # 检查 Excel 文件是否存在
        if not os.path.exists(EXCEL_PATH):
            logging.debug(f"[Error] 设备清单文件不存在，无法构建SN映射：{EXCEL_PATH}")
            return sn_relate_map

        # 读取第二个Excel的指定Sheet
        relate_df = pd.read_excel(EXCEL_PATH, sheet_name=RELATE_SHEET_NAME)

        # 校验关键列是否存在
        required_cols = [RELATE_SN_COL, RELATE_MODEL_COL, RELATE_IP_COL, RELATE_DC_COL]
        for col in required_cols:
            if col not in relate_df.columns:
                logging.debug(f"[Error] 第二个Excel的[{RELATE_SHEET_NAME}]Sheet缺少必要列：{col}")
                return sn_relate_map

        # 遍历第二个Excel，构建映射（去重：若有重复SN，取第一条数据）
        for _, row in relate_df.iterrows():
            # 提取SN并做空值处理
            sn_value = row.get(RELATE_SN_COL)
            if pd.isna(sn_value):
                continue  # 跳过空SN行
            sn_str = str(sn_value).strip()
            if sn_str in sn_relate_map:
                continue  # 已存在该SN，跳过重复数据

            # 提取model、ip、dc并做空值处理
            model_val = row.get(RELATE_MODEL_COL)
            model_str = str(model_val).strip() if pd.notna(model_val) else "未查询到型号"

            ip_val = row.get(RELATE_IP_COL)
            ip_str = str(ip_val).strip() if pd.notna(ip_val) else "未查询到IP"

            dc_val = row.get(RELATE_DC_COL)
            dc_str = str(dc_val).strip() if pd.notna(dc_val) else "未查询到数据中心"

            # 存入映射字典
            sn_relate_map[sn_str] = {
                "model": model_str,
                "ip": ip_str,
                "dc": dc_str
            }
    except FileNotFoundError:
        logging.error(f"[Error] 未找到Excel文件：{EXCEL_PATH}，SN映射字典为空")
    except Exception as e:
        logging.error(f"[Error] 构建SN映射字典失败：{str(e)}")

    return sn_relate_map

# 全局先构建映射字典（仅执行一次，提高效率）
sn_relate_dict = build_sn_relate_map()

@app.route('/topology/get_zones', methods=['GET'])
def get_zones():
    try:
        device_df = pd.read_excel(LLDP_EXCEL_PATH, sheet_name=LLDP_SHEET_NAME1)
        if LLDP_AREA_COL not in device_df.columns:
            return jsonify({"success": False, "error": f"{LLDP_SHEET_NAME1}缺少必要列：{LLDP_AREA_COL}"})
        zone_names = device_df[LLDP_AREA_COL].dropna().unique().tolist()
        zones = [{"id": str(z), "name": str(z)} for z in zone_names]
        return jsonify({"success": True, "zones": zones})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# 添加拓扑数据路由----------------
@app.route('/topology/get_dc_topology_data')
def get_dc_topology_data():
    try:
        data = get_or_load_cache('dc_topology_data')
        if isinstance(data, dict) and data.get('success') is False:
            return jsonify(data), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/topology/get_zone_topology_data')
def get_zone_topology_data():
    zone_id = request.args.get('zone_id')
    if not zone_id:
        return jsonify({"success": False, "error": "缺少参数 zone_id"}), 400
    data = get_cached_zone_topology(zone_id)
    # 防御：缓存可能因历史版本污染存入非 dict（如 Flask Response 对象），
    # 此时清缓存并重取，避免 jsonify(非 dict) 触发 500
    if not isinstance(data, dict):
        # logging.error("get_zone_topology_data 命中非 dict 缓存（疑似旧版本污染），已清除并重取：%s", zone_id)
        _ZONE_TOPOLOGY_CACHE.pop(zone_id, None)
        try:
            data = _fetch_zone_topology_data(zone_id)
        except Exception as e:
            return jsonify({"success": False, "error": f"获取分区拓扑失败：{str(e)}"}), 500
    # _fetch_zone_topology_data 现在统一返回 dict；status 字段携带 HTTP 状态码，缺省 200
    status = data.get('status', 200) if isinstance(data, dict) else 200
    return jsonify(data), status


# 添加保存拓扑坐标的路由-----------
@app.route('/topology/save_dc_topology', methods=['POST'])
def save_dc_topology():
    """
    保存总拓扑节点坐标到 LLDP 数据文件的「设备分区坐标表」中，分区固定为“总拓扑”
    请求 JSON 格式: {"devices": [{"name": "设备A", "x": 100, "y": 200}, ...]}
    """
    try:
        data = request.get_json()
        # logging.debug(f"收到的坐标保存数据：{data}")
        if not data:
            return jsonify({"success": False, "error": "请求体为空"}), 400

        devices = data.get('devices', [])
        if not isinstance(devices, list):
            return jsonify({"success": False, "error": "devices 应为数组"}), 400

        # 打开 LLDP Excel 工作簿
        if not os.path.exists(LLDP_EXCEL_PATH):
            return jsonify({"success": False, "error": f"LLDP 数据文件不存在：{LLDP_EXCEL_PATH}"}), 404

        wb = openpyxl.load_workbook(LLDP_EXCEL_PATH)
        if LLDP_SHEET_NAME2 not in wb.sheetnames:
            wb.close()
            return jsonify({"success": False, "error": f"Excel 中缺少工作表：{LLDP_SHEET_NAME2}"}), 400

        ws = wb[LLDP_SHEET_NAME2]

        # 定位列索引
        header_row = 1
        name_col = None
        zone_col = None
        x_col = None
        y_col = None

        for col in ws.iter_cols(min_row=header_row, max_row=header_row):
            for cell in col:
                val = str(cell.value).strip() if cell.value else ""
                if val == "设备名称":
                    name_col = cell.column
                elif val == "当前分区":
                    zone_col = cell.column
                elif val == LLDP_X_COL:
                    x_col = cell.column
                elif val == LLDP_Y_COL:
                    y_col = cell.column

        if name_col is None or zone_col is None:
            wb.close()
            return jsonify({"success": False, "error": "坐标表缺少「设备名称」或「当前分区」列"}), 400

        if x_col is None:
            x_col = ws.max_column + 1
            ws.cell(row=header_row, column=x_col, value=LLDP_X_COL)
        if y_col is None:
            y_col = ws.max_column + 1
            ws.cell(row=header_row, column=y_col, value=LLDP_Y_COL)

        # 构建 (设备名称, 分区) -> 行号 映射，只关注分区为“总拓扑”的行
        key_to_row = {}
        for row in range(header_row + 1, ws.max_row + 1):
            name_cell = ws.cell(row=row, column=name_col)
            zone_cell = ws.cell(row=row, column=zone_col)
            name = str(name_cell.value).strip() if name_cell.value else ""
            zone = str(zone_cell.value).strip() if zone_cell.value else ""
            if name and zone:
                key_to_row[(name, zone)] = row

        # 更新坐标
        updated = 0
        not_found = []
        target_zone = "总拓扑"

        for dev in devices:
            dev_name = dev.get('name')
            x = dev.get('x')
            y = dev.get('y')

            if not dev_name:
                continue
            if x is None and y is None:
                continue

            key = (dev_name, target_zone)
            if key not in key_to_row:
                not_found.append(dev_name)
                continue

            row = key_to_row[key]
            if x is not None:
                ws.cell(row=row, column=x_col, value=x)
            if y is not None:
                ws.cell(row=row, column=y_col, value=y)
            updated += 1

        # 保存
        wb.save(LLDP_EXCEL_PATH)
        wb.close()

        msg = f"{target_zone}:成功更新 {updated} 个设备的坐标"
        if not_found:
            msg += f"；以下设备未找到坐标记录：{', '.join(not_found)}"

        return jsonify({
            "success": True,
            "message": msg,
            "updated_count": updated,
            "not_found": not_found
        })

    except Exception as e:
        try:
            wb.close()
        except:
            pass
        return jsonify({
            "success": False,
            "error": f"保存坐标失败：{str(e)}"
        }), 500



@app.route('/topology/save_zone_topology', methods=['POST'])
def save_zone_topology():
    """
    保存分区拓扑节点坐标到 LLDP 数据文件的「设备分区坐标表」
    请求 JSON 格式: {"zone_id": "核心区", "devices": [{"name": "设备A", "x": 100, "y": 200}, ...]}
    """
    try:
        # ---------- 1. 解析请求数据 ----------
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "请求体为空"}), 400

        zone_id = data.get('zone_id')
        devices = data.get('devices', [])

        if not zone_id:
            return jsonify({"success": False, "error": "缺少 zone_id"}), 400
        if not isinstance(devices, list):
            return jsonify({"success": False, "error": "devices 应为数组"}), 400

        # ---------- 2. 加载 LLDP Excel 工作簿 ----------
        if not os.path.exists(LLDP_EXCEL_PATH):
            return jsonify({"success": False, "error": f"LLDP 数据文件不存在：{LLDP_EXCEL_PATH}"}), 404

        wb = openpyxl.load_workbook(LLDP_EXCEL_PATH)
        if LLDP_SHEET_NAME2 not in wb.sheetnames:
            wb.close()
            return jsonify({"success": False, "error": f"Excel 中缺少工作表：{LLDP_SHEET_NAME2}"}), 400

        ws = wb[LLDP_SHEET_NAME2]

        # ---------- 3. 定位关键列索引 ----------
        header_row = 1
        name_col = None      # 设备名称列
        zone_col = None      # 当前分区列
        x_col = None         # topology_x
        y_col = None         # topology_y

        for col in ws.iter_cols(min_row=header_row, max_row=header_row):
            for cell in col:
                val = str(cell.value).strip() if cell.value else ""
                if val == "设备名称":
                    name_col = cell.column
                elif val == "当前分区":
                    zone_col = cell.column
                elif val == LLDP_X_COL:
                    x_col = cell.column
                elif val == LLDP_Y_COL:
                    y_col = cell.column

        if name_col is None or zone_col is None:
            wb.close()
            return jsonify({"success": False, "error": "坐标表缺少「设备名称」或「当前分区」列"}), 400

        # 如果坐标列不存在，自动添加（理论应存在，防御性编程）
        if x_col is None:
            x_col = ws.max_column + 1
            ws.cell(row=header_row, column=x_col, value=LLDP_X_COL)
        if y_col is None:
            y_col = ws.max_column + 1
            ws.cell(row=header_row, column=y_col, value=LLDP_Y_COL)

        # ---------- 4. 构建 (设备名称, 分区) -> 行号 映射 ----------
        key_to_row = {}
        for row in range(header_row + 1, ws.max_row + 1):
            name_cell = ws.cell(row=row, column=name_col)
            zone_cell = ws.cell(row=row, column=zone_col)
            name = str(name_cell.value).strip() if name_cell.value else ""
            zone = str(zone_cell.value).strip() if zone_cell.value else ""
            if name and zone:
                key_to_row[(name, zone)] = row

        # ---------- 5. 更新坐标 ----------
        updated = 0
        not_found = []

        for dev in devices:
            dev_name = dev.get('name')
            x = dev.get('x')
            y = dev.get('y')

            if not dev_name:
                continue
            if x is None and y is None:
                continue   # 没有需要更新的坐标

            key = (dev_name, zone_id)
            if key not in key_to_row:
                not_found.append(dev_name)
                continue

            row = key_to_row[key]
            if x is not None:
                ws.cell(row=row, column=x_col, value=x)
            if y is not None:
                ws.cell(row=row, column=y_col, value=y)
            updated += 1

        # ---------- 6. 保存并关闭 ----------
        wb.save(LLDP_EXCEL_PATH)
        wb.close()

        msg = f"{zone_id}:成功更新 {updated} 个设备的坐标"
        if not_found:
            msg += f"；未找到以下设备在当前分区的记录：{', '.join(not_found)}"

        return jsonify({
            "success": True,
            "message": msg,
            "updated_count": updated,
            "not_found": not_found
        })

    except Exception as e:
        # 确保工作簿关闭
        try:
            wb.close()
        except:
            pass
        return jsonify({
            "success": False,
            "error": f"保存坐标失败：{str(e)}"
        }), 500



# 加载拓扑管理页面----------------
@app.route('/topology/topology_dc')
def topology_dc():
    print(f"=== 用户  访问总拓扑管理 ===")  
    return render_template('topology_dc.html')

@app.route('/topology/topology_zone')
def topology_zone():
    print(f"=== 用户  访问分区拓扑管理 ===")  
    return render_template('topology_zone.html')

@app.route('/topology/topology_dc2')
def topology_dc2():
    print(f"=== 用户  访问拓扑2管理 ===")  
    return render_template('topology_dc2.html')


##### 批量脚本生成管理路由 #####


# 检查文件扩展名是否允许
def allowed_file(filename, allowed_extensions):
    """检查文件扩展名是否允许"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

# 获取文件大小（KB）
def get_file_size(file_path):
    """获取文件大小（KB）"""
    if os.path.exists(file_path):
        return round(os.path.getsize(file_path) / 1024, 2)
    return 0

# 获取文件修改时间
def get_file_modified_time(file_path):
    """获取文件修改时间"""
    if os.path.exists(file_path):
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(file_path)))
    return ''

# 获取模板文件列表
def get_template_list():
    """获取所有模板文件列表"""
    template_files = []
    for filename in os.listdir(app.config['TEMPLATE_UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['TEMPLATE_UPLOAD_FOLDER'], filename)
        if os.path.isfile(file_path) and allowed_file(filename, app.config['ALLOWED_TEMPLATE_EXTENSIONS']):
            template_files.append({
                'filename': filename,
                'size': get_file_size(file_path),
                'upload_time': get_file_modified_time(file_path)
            })
    # 按上传时间排序，最新的在前
    template_files.sort(key=lambda x: x['upload_time'], reverse=True)
    return template_files

# 获取设备名称映射表列表
@app.route('/get_device_mappings')
def get_device_mappings():
    """获取所有设备名称映射表列表"""
    device_mappings = get_device_mappings_list()
    return jsonify({
        "success": True,
        "device_mappings": device_mappings
    })

def get_device_mappings_list():
    """获取所有设备名称映射表列表"""
    device_mappings = []
    for filename in os.listdir(app.config['ASSET_INFO_FOLDER']):
        file_path = os.path.join(app.config['ASSET_INFO_FOLDER'], filename)
        if os.path.isfile(file_path) and allowed_file(filename, app.config['ALLOWED_DEVICE_MAPPING_EXTENSIONS']):
            device_mappings.append({
                'filename': filename
            })
    return device_mappings

# 获取数据源文件列表
def get_data_list():
    """获取所有数据源文件列表"""
    data_files = []
    for filename in os.listdir(app.config['DATA_UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['DATA_UPLOAD_FOLDER'], filename)
        if os.path.isfile(file_path) and allowed_file(filename, app.config['ALLOWED_DATA_EXTENSIONS']):
            data_files.append({
                'filename': filename,
                'size': get_file_size(file_path),
                'upload_time': get_file_modified_time(file_path)
            })
    # 按上传时间排序，最新的在前
    data_files.sort(key=lambda x: x['upload_time'], reverse=True)
    return data_files

def get_asset_info_list():
    """获取 asset_info 目录下的所有 json 和 xlsx 文件列表"""
    files = []
    folder = app.config['ASSET_INFO_FOLDER']
    allowed_ext = app.config['ALLOWED_ASSET_INFO_EXTENSIONS']
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        if os.path.isfile(file_path) and allowed_file(filename, allowed_ext):
            files.append({
                'filename': filename,
                'size': get_file_size(file_path),
                'upload_time': get_file_modified_time(file_path)
            })
    files.sort(key=lambda x: x['upload_time'], reverse=True)
    return files

@app.route('/get_asset_info_files')
def get_asset_info_files():
    """返回 asset_info 目录下的文件列表 JSON"""
    files = get_asset_info_list()
    return jsonify({'success': True, 'files': files})

@app.route('/upload_asset_info', methods=['POST'])
def upload_asset_info():
    """上传资产信息文件（json/xlsx）"""
    files = request.files.getlist('asset_info_file')
    for file in files:
        if file.filename == '':
            flash('有文件未选择名称', 'error')
            continue
        if file and allowed_file(file.filename, app.config['ALLOWED_ASSET_INFO_EXTENSIONS']):
            filename = safe_upload_filename(file.filename)
            base, ext = os.path.splitext(filename)
            counter = 1
            save_path = app.config['ASSET_INFO_FOLDER']
            while os.path.exists(os.path.join(save_path, filename)):
                filename = f"{base}_{counter}{ext}"
                counter += 1
            file.save(os.path.join(save_path, filename))
            flash(f'资产信息文件 "{filename}" 上传成功', 'success')
        else:
            flash(f'文件 "{file.filename}" 格式不支持，仅支持 {app.config["ALLOWED_ASSET_INFO_EXTENSIONS"]}', 'error')
    return redirect(url_for('template_file'))

@app.route('/download_asset_info/<filename>')
def download_asset_info(filename):
    """下载资产信息文件"""
    return send_from_directory(app.config['ASSET_INFO_FOLDER'], filename, as_attachment=True)

@app.route('/delete_asset_info/<filename>', methods=['DELETE'])
def delete_asset_info(filename):
    """删除资产信息文件"""
    file_path = os.path.join(app.config['ASSET_INFO_FOLDER'], filename)
    if os.path.exists(file_path) and allowed_file(filename, app.config['ALLOWED_ASSET_INFO_EXTENSIONS']):
        os.remove(file_path)
        return jsonify({'success': True, 'message': f'文件 "{filename}" 已删除'})
    return jsonify({'success': False, 'message': '文件不存在或格式不匹配'}), 404

@app.route('/open_asset_info_dir')
def open_asset_info_dir():
    """打开 asset_info 目录"""
    full_path = app.config['ASSET_INFO_FOLDER']
    return open_local_dir2(full_path)   # 复用已有的打开目录函数


def get_custom_line_list():
    """获取自定义云专线目录下的所有文件列表"""
    files = []
    folder = app.config['CUSTOM_LINE_FOLDER']
    allowed_ext = app.config['ALLOWED_CUSTOM_LINE_EXTENSIONS']
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        if os.path.isfile(file_path) and allowed_file(filename, allowed_ext):
            files.append({
                'filename': filename,
                'size': get_file_size(file_path),
                'upload_time': get_file_modified_time(file_path)
            })
    files.sort(key=lambda x: x['upload_time'], reverse=True)
    return files

@app.route('/get_custom_lines')
def get_custom_lines():
    """返回自定义云专线目录的文件列表 JSON"""
    files = get_custom_line_list()
    return jsonify({'success': True, 'files': files})

@app.route('/get_custom_line_files')
def get_custom_line_files():
    """返回自定义云专线目录下的文件名列表（用于下拉框）"""
    folder = app.config['CUSTOM_LINE_FOLDER']
    allowed_ext = app.config['ALLOWED_CUSTOM_LINE_EXTENSIONS']
    files = []
    for f in os.listdir(folder):
        if os.path.isfile(os.path.join(folder, f)) and allowed_file(f, allowed_ext):
            files.append(f)
    return jsonify({'success': True, 'files': files})

@app.route('/upload_custom_line', methods=['POST'])
def upload_custom_line():
    """上传自定义云专线文件"""
    files = request.files.getlist('custom_line_file')
    for file in files:
        if file.filename == '':
            flash('有文件未选择名称', 'error')
            continue
        if file and allowed_file(file.filename, app.config['ALLOWED_CUSTOM_LINE_EXTENSIONS']):
            filename = safe_upload_filename(file.filename)
            base, ext = os.path.splitext(filename)
            counter = 1
            save_path = app.config['CUSTOM_LINE_FOLDER']
            while os.path.exists(os.path.join(save_path, filename)):
                filename = f"{base}_{counter}{ext}"
                counter += 1
            file.save(os.path.join(save_path, filename))
            flash(f'自定义云专线文件 "{filename}" 上传成功', 'success')
        else:
            flash(f'文件 "{file.filename}" 格式不支持，仅支持 {app.config["ALLOWED_CUSTOM_LINE_EXTENSIONS"]}', 'error')
    return redirect(url_for('template_file'))

@app.route('/delete_custom_line/<filename>', methods=['DELETE'])
def delete_custom_line(filename):
    """删除自定义云专线文件"""
    file_path = os.path.join(app.config['CUSTOM_LINE_FOLDER'], filename)
    if os.path.exists(file_path) and allowed_file(filename, app.config['ALLOWED_CUSTOM_LINE_EXTENSIONS']):
        os.remove(file_path)
        return jsonify({'success': True, 'message': f'文件 "{filename}" 已删除'})
    return jsonify({'success': False, 'message': '文件不存在或格式不匹配'}), 404

@app.route('/download_custom_line/<filename>')
def download_custom_line(filename):
    """下载自定义云专线文件"""
    return send_from_directory(app.config['CUSTOM_LINE_FOLDER'], filename, as_attachment=True)

@app.route('/open_custom_line_dir')
def open_custom_line_dir():
    """打开自定义云专线目录"""
    full_path = app.config['CUSTOM_LINE_FOLDER']
    return open_local_dir2(full_path)  # 复用已有的打开目录函数


# 获取生成脚本文件列表 包含子目录
def get_script_tree(base_dir, rel_path=''):
    """递归获取目录树，仅包含允许扩展名的文件（与之前相同，无需改动）"""
    full_path = os.path.join(base_dir, rel_path)
    if not os.path.isdir(full_path):
        return []

    items = []
    allowed_extensions = app.config.get('ALLOWED_TEMPLATE_EXTENSIONS', {'txt'})
    try:
        for entry in os.listdir(full_path):
            entry_full = os.path.join(full_path, entry)
            entry_rel = os.path.join(rel_path, entry) if rel_path else entry

            if os.path.isdir(entry_full):
                children = get_script_tree(base_dir, entry_rel)
                items.append({
                    'type': 'dir',
                    'name': entry,
                    'rel_path': entry_rel,
                    'children': children
                })
            else:
                ext = os.path.splitext(entry)[1][1:].lower()
                if not allowed_extensions or ext in allowed_extensions:
                    stat = os.stat(entry_full)
                    items.append({
                        'type': 'file',
                        'name': entry,
                        'rel_path': entry_rel,
                        'size': round(stat.st_size / 1024, 2),
                        'mtime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                    })
    except PermissionError:
        pass
    # 文件夹在前，按名称排序
    items.sort(key=lambda x: (0 if x['type'] == 'dir' else 1, x['name'].lower()))
    return items



# 获取生成脚本文件列表(暂时未使用)
def get_script_list():
    script_files = []
    for filename in os.listdir(app.config['RESULTS_FOLDER']):
        file_path = os.path.join(app.config['RESULTS_FOLDER'], filename)
        if os.path.isfile(file_path) and allowed_file(filename, app.config['ALLOWED_TEMPLATE_EXTENSIONS']):
            script_files.append({
                'filename': filename,
                'size': get_file_size(file_path),
                'upload_time': get_file_modified_time(file_path)
            })
    # 按上传时间排序，最新的在前
    script_files.sort(key=lambda x: x['upload_time'], reverse=True)
    return script_files



# 获取生成脚本文件列表 
@app.route('/get_scripts')
def get_scripts():
    """返回生成目录的树形结构"""
    try:
        results_folder = app.config['RESULTS_FOLDER']
        tree = get_script_tree(results_folder)
        return jsonify({'success': True, 'tree': tree})
    except Exception as e:
        app.logger.error(f'获取脚本列表失败：{str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get_dir_list')
def get_dir_list():
    path = request.args.get('path', '')  # 相对路径，相对于 RESULTS_FOLDER
    base_dir = app.config['RESULTS_FOLDER']
    full_path = os.path.join(base_dir, path)
    
    if '..' in path or path.startswith('/'):
        return jsonify({'success': False, 'message': '非法路径'}), 400
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': '目录不存在'}), 404
    if not os.path.isdir(full_path):
        return jsonify({'success': False, 'message': '路径不是目录'}), 400

    items = []
    allowed_extensions = app.config.get('ALLOWED_TEMPLATE_EXTENSIONS', {'txt'})
    try:
        for entry in os.listdir(full_path):
            entry_full = os.path.join(full_path, entry)
            entry_rel = os.path.join(path, entry) if path else entry
            
            if os.path.isdir(entry_full):
                items.append({
                    'type': 'dir',
                    'name': entry,
                    'rel_path': entry_rel,
                })
            else:
                ext = os.path.splitext(entry)[1][1:].lower()
                if not allowed_extensions or ext in allowed_extensions:
                    stat = os.stat(entry_full)
                    items.append({
                        'type': 'file',
                        'name': entry,
                        'rel_path': entry_rel,
                        'size': round(stat.st_size / 1024, 2),
                        'mtime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                    })
    except PermissionError:
        return jsonify({'success': False, 'message': '权限不足'}), 403
    
    items.sort(key=lambda x: (0 if x['type'] == 'dir' else 1, x['name'].lower()))
    breadcrumb = path.split('/') if path else []
    
    return jsonify({
        'success': True,
        'items': items,
        'current_path': path,
        'breadcrumb': breadcrumb,
        'parent_path': '/'.join(breadcrumb[:-1]) if breadcrumb else ''
    })



@app.route('/open_local_dir')
def open_local_dir():
    """打开 RESULTS_FOLDER 下的指定子目录（由 scene_batch 调用）"""
    path = request.args.get('path', '')
    # 安全检查，防止路径穿越
    if '..' in path or path.startswith('/'):
        return jsonify({'success': False, 'message': '非法路径'}), 400

    base_dir = app.config['RESULTS_FOLDER']
    full_path = os.path.join(base_dir, path)
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': '目录不存在'}), 404
    if not os.path.isdir(full_path):
        return jsonify({'success': False, 'message': '路径不是目录'}), 400

    try:
        system = platform.system()
        if system == 'Windows':
            os.startfile(full_path)
        elif system == 'Darwin':  # macOS
            subprocess.Popen(['open', full_path])
        else:  # Linux
            subprocess.Popen(['xdg-open', full_path])
        return jsonify({'success': True, 'message': f'已打开目录: {full_path}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'打开目录失败: {str(e)}'}), 500


# 上传模板文件-----------------------
@app.route('/upload_template', methods=['POST'])
def upload_template():
    """上传模板文件"""
    
    files = request.files.getlist('template_file')
    
    for file in files:
        if file.filename == '':
            flash('有文件未选择名称', 'error')
            continue
            
        if file and allowed_file(file.filename, app.config['ALLOWED_TEMPLATE_EXTENSIONS']):
            filename = safe_upload_filename(file.filename)
            # 处理同名文件
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(app.config['TEMPLATE_UPLOAD_FOLDER'], filename)):
                filename = f"{base}_{counter}{ext}"
                counter += 1
                
            file.save(os.path.join(app.config['TEMPLATE_UPLOAD_FOLDER'], filename))
            flash(f'模板文件 "{filename}" 上传成功', 'success')
        else:
            flash(f'文件 "{file.filename}" 格式不支持，仅支持 {app.config["ALLOWED_TEMPLATE_EXTENSIONS"]}', 'error')
    
    return redirect(url_for('template_file'))

# 上传数据源文件-----------------------
@app.route('/upload_datasource', methods=['POST'])
def upload_datasource():
    """上传数据源文件"""
    
    files = request.files.getlist('dataSource_file')
    for file in files:
        if file.filename == '':
            flash('有文件未选择名称', 'error')
            continue
            
        if file and allowed_file(file.filename, app.config['ALLOWED_DATA_EXTENSIONS']):
            filename = safe_upload_filename(file.filename)
            # 处理同名文件
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(app.config['DATA_UPLOAD_FOLDER'], filename)):
                filename = f"{base}_{counter}{ext}"
                counter += 1
                
            file.save(os.path.join(app.config['DATA_UPLOAD_FOLDER'], filename))
            flash(f'数据源文件 "{filename}" 上传成功', 'success')
        else:
            flash(f'文件 "{file.filename}" 格式不支持，仅支持 {app.config["ALLOWED_DATA_EXTENSIONS"]}', 'error')
        
    return redirect(url_for('template_file'))

# 查看模板文件-----------------------
@app.route('/view_template/<filename>')
def view_template(filename):
    """查看模板文件"""
    return send_from_directory(app.config['TEMPLATE_UPLOAD_FOLDER'], filename, as_attachment=False)  # false是支持预览，true为下载

# 查看生成脚本文件-----------------------
@app.route('/view_script/<path:filename>')
def view_script(filename):
    """查看脚本（支持子目录）"""
    if '..' in filename or filename.startswith('/'):
        return "非法路径", 400
    file_path = os.path.join(app.config['RESULTS_FOLDER'], filename)
    if not os.path.isfile(file_path):
        return "文件不存在", 404
    return send_file(file_path, as_attachment=False)


# 下载模板文件-----------------------
@app.route('/download_template/<filename>')
def download_template(filename):
    """下载模板文件"""
    return send_from_directory(app.config['TEMPLATE_UPLOAD_FOLDER'], filename, as_attachment=True)

# 下载数据源文件-----------------------
@app.route('/download_datasource/<filename>')
def download_datasource(filename):
    """下载数据源文件"""
    if '..' in filename or filename.startswith('/'):
        return "非法路径", 400
    file_path = os.path.join(app.config['DATA_UPLOAD_FOLDER'], filename)
    if not os.path.isfile(file_path):
        return "文件不存在", 404
    return send_file(file_path, as_attachment=True)

# 下载生成脚本文件-----------------------
@app.route('/download_script/<path:filename>')
def download_script(filename):
    """下载脚本（支持子目录）"""
    if '..' in filename or filename.startswith('/'):
        return "非法路径", 400
    file_path = os.path.join(app.config['RESULTS_FOLDER'], filename)
    if not os.path.isfile(file_path):
        return "文件不存在", 404
    return send_file(file_path, as_attachment=True)


# 删除模板文件-----------------------
@app.route('/delete_template/<filename>', methods=['DELETE'])
def delete_template(filename):
    """删除模板文件"""
    try:
        file_path = os.path.join(app.config['TEMPLATE_UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path) and allowed_file(filename, app.config['ALLOWED_TEMPLATE_EXTENSIONS']):
            os.remove(file_path)
            return jsonify({'success': True, 'message': f'模板文件 "{filename}" 已删除'})
        else:
            return jsonify({'success': False, 'message': f'模板文件 "{filename}" 不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500

# 删除数据源文件-----------------------
@app.route('/delete_datasource/<filename>', methods=['DELETE'])
def delete_datasource(filename):
    """删除数据源文件"""
    try:
        file_path = os.path.join(app.config['DATA_UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path) and allowed_file(filename, app.config['ALLOWED_DATA_EXTENSIONS']):
            os.remove(file_path)
            return jsonify({'success': True, 'message': f'数据源文件 "{filename}" 已删除'})
        else:
            return jsonify({'success': False, 'message': f'数据源文件 "{filename}" 不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500

# 删除生成脚本文件-----------------------
@app.route('/delete_script/<path:filename>', methods=['DELETE'])
def delete_script(filename):
    """删除脚本（支持子目录）"""
    if '..' in filename or filename.startswith('/'):
        return jsonify({'success': False, 'message': '非法路径'}), 400
    file_path = os.path.join(app.config['RESULTS_FOLDER'], filename)
    if os.path.isfile(file_path):
        os.remove(file_path)
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': '文件不存在'})


# 删除所有生成脚本文件-----------------------
@app.route('/delete_all', methods=['DELETE'])
def delete_all():
    """递归删除 RESULTS_FOLDER 下的所有文件和子目录（保留根目录）"""
    target_dir = app.config['RESULTS_FOLDER']
    if not os.path.exists(target_dir):
        return jsonify({'success': False, 'message': '目录不存在'}), 404
    if not os.path.isdir(target_dir):
        return jsonify({'success': False, 'message': '路径不是目录'}), 400
    
    try:
        # 删除所有内容，但保留目录本身
        for item in os.listdir(target_dir):
            item_path = os.path.join(target_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        return jsonify({'success': True, 'message': '已清空所有文件'})
    except Exception as e:
        app.logger.error(f'清空目录失败：{str(e)}')
        return jsonify({'success': False, 'message': f'删除失败：{str(e)}'}), 500
    

# 获取Excel文件的所有sheet名称-----------------------
@app.route('/get_sheets')
def get_sheets():
    """获取Excel文件的所有sheet名称"""
    try:
        file_name = request.args.get('file')
        if not file_name:
            return jsonify({'success': False, 'message': '未指定文件'}), 400
            
        file_path = os.path.join(app.config['DATA_UPLOAD_FOLDER'], file_name)
        if not os.path.exists(file_path) or not allowed_file(file_name, app.config['ALLOWED_DATA_EXTENSIONS']):
            return jsonify({'success': False, 'message': '文件不存在或格式不支持'}), 404
            
        # 读取Excel文件的所有sheet名称
        excel_file = pd.ExcelFile(file_path)
        sheets = excel_file.sheet_names
        
        return jsonify({'success': True, 'sheets': sheets})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取sheet失败: {str(e)}'}), 500


# 下载所有生成的脚本-----------------------
@app.route('/download_all')
def download_all():
    """下载所有脚本（包括子目录，打包为ZIP）"""
    memory_file = BytesIO()
    results_root = app.config['RESULTS_FOLDER']
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for dirpath, dirnames, filenames in os.walk(results_root):
            for f in filenames:
                if allowed_file(f, app.config['ALLOWED_TEMPLATE_EXTENSIONS']):
                    full_path = os.path.join(dirpath, f)
                    # 计算相对路径（相对于结果目录）
                    arcname = os.path.relpath(full_path, results_root)
                    zipf.write(full_path, arcname)
    memory_file.seek(0)
    dir_name = RESULTS_FOLDER
    current_time_str = datetime.now().strftime("%Y%m%d%H%M%S")
    zip_filename = f"{dir_name}_{current_time_str}.zip"
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_filename
    )


# 获取数据源文件名称
def get_datasource_name():
    """获取所有数据源文件名称"""
    file_names = []
    for filename in os.listdir(app.config['DATA_UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['DATA_UPLOAD_FOLDER'], filename)
        if os.path.isfile(file_path) and allowed_file(filename, app.config['ALLOWED_DATA_EXTENSIONS']):
            file_names.append({
                'filename': filename,
            })
    
    return file_names

# 获取sheet名称-----------------------
@app.route('/get_sheet_name')
def get_sheet_name():
    """前端请求获取指定Excel文件的sheet列表"""
    filename = request.args.get('filename')
    # logging.debug(f"请求的文件名：{filename}")
    file_path = os.path.join(app.config['DATA_UPLOAD_FOLDER'], filename)
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheets = wb.sheetnames  # 获取所有sheet名称
    wb.close()  # 手动关闭工作簿，释放资源
    # logging.debug(f"获取到的sheet列表：{sheets}")
    return jsonify({'sheets': sheets})



@app.route('/get_data_sources')
def get_data_sources():
    """返回 data_uploads 目录下的文件列表 JSON"""
    files = get_data_list()  # 复用你已有的 get_data_list 函数
    return jsonify({'success': True, 'files': files})

@app.route('/get_templates')
def get_templates():
    """返回 templates_uploads 目录下的文件列表 JSON"""
    files = get_template_list()  # 复用已有的 get_template_list
    return jsonify({'success': True, 'files': files})

@app.route('/open_data_dir')
def open_data_dir():
    full_path = app.config['DATA_UPLOAD_FOLDER']
    return open_local_dir2(full_path)

@app.route('/open_template_dir')
def open_template_dir():
    full_path = app.config['TEMPLATE_UPLOAD_FOLDER']
    return open_local_dir2(full_path)

def open_local_dir2(full_path):
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': '目录不存在'}), 404
    try:
        system = platform.system()
        if system == 'Windows':
            os.startfile(full_path)
        elif system == 'Darwin':
            subprocess.Popen(['open', full_path])
        else:
            subprocess.Popen(['xdg-open', full_path])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# 模板文件列表页面------------------
@app.route('/work/template_file')
def template_file():
    print(f"=== 用户  访问模板文件列表页面 ===") 
    templates = get_template_list()
    data_sources = get_data_list()
    custom_lines = get_custom_line_list() 
    asset_info_files = get_asset_info_list()  
    return render_template('template_file.html', templates=templates, data_sources=data_sources, custom_lines=custom_lines, asset_info_files=asset_info_files)


# 加载场景化批量脚本生成页面----------------
@app.route('/work/scene_batch')
def scene_batch():
    print(f"=== 用户  访问场景化批量脚本生成页面 ===") 
    device_mappings = get_device_mappings_list()
    data_sources = get_data_list()
    script_files = get_script_list()
    file_names = get_datasource_name()
    # logging.debug(f"获取选择结果：{device_mappings}")
    return render_template('scene_batch.html',device_mappings=device_mappings, data_sources=data_sources, script_files=script_files, file_names=file_names)


# 生成按钮点击事件-----------------------
@app.route('/generate_scripts', methods=['POST', 'GET'])
def generate_scripts():
    """处理生成脚本的POST请求"""

    # 获取 JSON 数据
    data = request.get_json()
    if data is None:
        return jsonify({'success': False, 'msg': '请求体必须是 JSON 格式'}), 400
    GLOBAL_DEVICE_MAPPING = data.get('devicemappinginfo')
    GLOBAL_DEVICE_INFO = os.path.join(app.config['ASSET_INFO_FOLDER'], GLOBAL_DEVICE_MAPPING)
    FILE_PATH = data.get('datasource')

    EXCEL_NAME = os.path.join(data_upload_dir, FILE_PATH)

    SHEET_NAME = data.get('sheetname')
    CUSTOM_LINE = data.get('customline')
    OUTPUT_DIR = app.config['RESULTS_FOLDER']
    ROLLBACK_DIR = os.path.join(OUTPUT_DIR, "回退脚本")
    CUSTOM_LINE_DIR = app.config['CUSTOM_LINE_FOLDER']
    TEMPLATE_DIR = app.config['TEMPLATE_UPLOAD_FOLDER']

    if "FW" in FILE_PATH:
        print(f"=== 准备处理FW脚本批量生成_虚墙场景 ===") 
        vsys_process.main(EXCEL_NAME, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, GLOBAL_DEVICE_INFO)
        print(f"=== 已完成FW脚本批量生成_虚墙场景 ===") 
    elif "三层" in FILE_PATH:
        print(f"=== 准备处理CE脚本批量生成_三层场景 ===") 
        ce_L3_process.main(EXCEL_NAME, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, GLOBAL_DEVICE_INFO)
        print(f"=== 已完成CE脚本批量生成_三层场景 ===") 
    elif "二层" in FILE_PATH:
        print(f"=== 准备处理CE脚本批量生成_二层场景 ===") 
        ce_L2_process.main(EXCEL_NAME, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, TEMPLATE_DIR, GLOBAL_DEVICE_INFO)
        print(f"=== 已完成CE脚本批量生成_二层场景 ===") 
    elif "自定义" in FILE_PATH or "云专线" in FILE_PATH:
        print(f"=== 准备处理自定义云专线脚本批量生成 ===") 
        cloud_process.main(EXCEL_NAME, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, CUSTOM_LINE_DIR, CUSTOM_LINE)
        print(f"=== 已完成自定义云专线脚本批量生成 ===") 
    elif "静态路由" in FILE_PATH:
        print(f"=== 准备处理静态路由脚本批量生成 ===") 
        static_process.main(EXCEL_NAME, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR)
        print(f"=== 已完成静态路由脚本批量生成 ===") 
    else:
        return jsonify({'success': False, 'message': '未执行任何操作'}), 400
        
    return jsonify({'success': True})


# ----------- 文本排序对比页面函数-开始 -----------

# 加载文本排序对比页面----------------
@app.route('/work/text_compare')
def text_compare():
    print(f"=== 用户  访问文本排序对比页面 ===") 
    return render_template('text_compare.html')

# ----------- 文本排序对比页面函数-结束 -----------


def _load_device_model_count():
    df = stat_device_df()
    series = df.groupby("设备型号").size()
    return {
        "code": 200,
        "msg": "success",
        "data": series.to_dict(),
        "total": int(series.sum())
    }

def _load_business_zone_count():
    df = stat_device_df()
    series = df.groupby("业务分区").size()
    return {
        "code": 200,
        "msg": "success",
        "data": series.to_dict(),
        "total": int(series.sum())
    }

# ===== 拓扑数据加载器 =====
def _load_dc_topology_data():
    """加载总拓扑数据，返回与 /topology/get_dc_topology_data 相同的字典"""
    try:
        # 1. 读取 LLDP 生成的三个 sheet
        base_df = pd.read_excel(LLDP_EXCEL_PATH, sheet_name=LLDP_SHEET_NAME1, dtype=str)
        coord_df = pd.read_excel(LLDP_EXCEL_PATH, sheet_name=LLDP_SHEET_NAME2, dtype=str)
        link_df = pd.read_excel(LLDP_EXCEL_PATH, sheet_name=LLDP_SHEET_NAME3, dtype=str)
    except FileNotFoundError:
        return jsonify({"success": False, "error": f"LLDP 数据文件不存在：{LLDP_EXCEL_PATH}"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": f"读取 LLDP Excel 失败：{str(e)}"}), 500

    # 列名标准化（去除首尾空格）
    base_df.columns = base_df.columns.str.strip()
    coord_df.columns = coord_df.columns.str.strip()
    link_df.columns = link_df.columns.str.strip()

    # 2. 校验必要列
    if "设备名称" not in base_df.columns:
        return jsonify({"success": False, "error": "基础信息表缺少「设备名称」列"}), 400
    if LLDP_Global_COL not in base_df.columns:
        return jsonify({"success": False, "error": "基础信息表缺少「是否在总拓扑体现」列"}), 400

    # 3. 筛选出在总拓扑中体现的设备
    base_df = base_df[base_df[LLDP_Global_COL].astype(str).str.strip() == "是"]
    if base_df.empty:
        return jsonify({"success": True, "nodes": [], "links": [], "message": "没有需要展示的设备"})

    # 去重并建立基础信息索引
    base_df = base_df.drop_duplicates(subset=["设备名称"], keep="first")
    base_df.set_index("设备名称", inplace=True)
    device_names = set(base_df.index)
    # logging.debug(base_df)
    # logging.debug("111")
    # logging.debug(device_names)
    # logging.debug("222")
    # 4. 从互联表中筛选两端都在总拓扑设备集合中的链路
    link_df = link_df.dropna(subset=["本端设备名称", "远端设备名称"])
    link_df["本端设备名称"] = link_df["本端设备名称"].astype(str).str.strip()
    link_df["远端设备名称"] = link_df["远端设备名称"].astype(str).str.strip()
    mask = link_df["本端设备名称"].isin(device_names) & link_df["远端设备名称"].isin(device_names)
    link_df = link_df[mask]
    # logging.debug(link_df)
    # 5. 从坐标表中获取“总拓扑”分区的坐标（处理 NaN）
    coord_df = coord_df[coord_df["当前分区"].astype(str).str.strip() == "总拓扑"]
    coord_map = {}
    for _, row in coord_df.iterrows():
        dev = str(row["设备名称"]).strip()
        if dev:
            x_val = row.get("topology_x")
            y_val = row.get("topology_y")
            # 转换为 float，无效则 None
            try:
                x = x_val if pd.notna(x_val) and x_val not in (None, "", "NaN", "nan") else None
            except (ValueError, TypeError):
                x = None

            try:
                y = y_val if pd.notna(y_val) and y_val not in (None, "", "NaN", "nan") else None
            except (ValueError, TypeError):
                y = None
            coord_map[dev] = (x, y)

    # 6. 从设备清单补充信息（可选）
    try:
        relate_df = pd.read_excel(EXCEL_PATH, sheet_name=RELATE_SHEET_NAME, dtype=str)
        relate_df.columns = relate_df.columns.str.strip()
        relate_df = relate_df.drop_duplicates(subset=[RELATE_NAME_COL], keep="first")
        relate_df.set_index(RELATE_NAME_COL, inplace=True)
    except Exception as e:
        relate_df = pd.DataFrame()
        logging.error(f"读取设备清单失败，将使用默认值：{str(e)}")

    # 辅助函数：安全获取字符串（NaN 转为空字符串）
    def safe_str(val):
        return str(val).strip() if pd.notna(val) else ""

    # 7. 构建节点列表
    nodes = []
    for dev in device_names:
        row = base_df.loc[dev]
        node = {
            "id": dev,
            "name": dev,
            "sn": safe_str(row.get("序列号SN", "")),
            "mac": safe_str(row.get("MAC地址", "")),
            "area": safe_str(row.get("所属分区", "")),
            "data_center": safe_str(row.get("所属数据中心", "")),  # 前端需要 data_center
            "vendor": safe_str(row.get("所属厂商", "")),
            "model": safe_str(row.get("设备型号", "")),
            "ip": safe_str(row.get("管理地址", "")),
            "type": safe_str(row.get("设备类型", "")), 
            "baseSize": 1,      # 供前端使用
            "hoverSize": 1,
        }

        # 从设备清单补充字段（若存在且非空）
        if not relate_df.empty and dev in relate_df.index:
            r = relate_df.loc[dev]
            # node["vendor"] = safe_str(r.get(RELATE_VENDOR_COL, node["vendor"]))
            # node["model"] = safe_str(r.get(RELATE_MODEL_COL, node["model"]))
            # node["ip"] = safe_str(r.get(RELATE_IP_COL, node["ip"]))
            # node["data_center"] = safe_str(r.get(RELATE_DC_COL, node["data_center"]))
            # node["area"] = safe_str(r.get(RELATE_AREA_COL, node["area"]))

        # 添加坐标（已处理为 None 或 float）
        x, y = coord_map.get(dev, (None, None))
        node["x"] = x
        node["y"] = y

        nodes.append(node)

    # 8. 构建链路列表（去重）
    links = []
    seen = set()
    for _, row in link_df.iterrows():
        local_dev = safe_str(row["本端设备名称"])
        local_intf = safe_str(row["本端设备接口"])
        remote_dev = safe_str(row["远端设备名称"])
        remote_intf = safe_str(row["远端设备接口"])

        if not local_dev or not remote_dev:
            continue

        conn1 = f"{local_dev}|{local_intf}"
        conn2 = f"{remote_dev}|{remote_intf}"
        sorted_conns = sorted([conn1, conn2])
        link_id = "|".join(sorted_conns)

        if link_id in seen:
            continue
        seen.add(link_id)

        links.append({
            "id": link_id,
            "source": local_dev,
            "target": remote_dev,
            "interface": f"{local_intf} ↔ {remote_intf}",
            "local_intf": local_intf,
            "remote_intf": remote_intf,
        })

    return {
        "success": True,
        "nodes": nodes,
        "links": links,
    }  

def _get_all_zone_names():
    """从 LLDP 数据中读取所有唯一的分区名称"""
    try:
        base_df = pd.read_excel(LLDP_EXCEL_PATH, sheet_name=LLDP_SHEET_NAME1, dtype=str)
        if LLDP_AREA_COL not in base_df.columns:
            return []
        zones = base_df[LLDP_AREA_COL].dropna().unique().tolist()
        return [str(z).strip() for z in zones if str(z).strip()]
    except Exception as e:
        print(f"[错误] 读取分区列表失败: {e}")
        return []

# ===================== 注册缓存加载器 =====================
register_loader('dc_status', stat_device_count)
register_loader('maintenance_status', check_maintenance_expired)
register_loader('eos_status', _eos_status_compute)
register_loader('manufacturer_status', check_manufacturer_status)
register_loader('device_model_list', filter_device_model)
register_loader('business_zone_list', filter_fenqu)
register_loader('device_model_count', _load_device_model_count)
register_loader('business_zone_count', _load_business_zone_count)
register_loader('dc_topology_data', _load_dc_topology_data)


host = '127.0.0.1'
port = 5001

def initialize_cache():
    """执行缓存预加载（由启动器或主入口调用）"""
    if PRELOAD_ON_STARTUP:
        with app.app_context():
            print("[策略] 正在预加载所有数据缓存（启动较慢，但运行丝滑）")
            for key in _CACHE_LOADERS.keys():
                try:
                    get_or_load_cache(key)
                    print(f"[缓存] {get_cache_display_name(key)} 加载完成")
                except Exception as e:
                    print(f"[错误] {key} 加载失败: {e}")
                    sys.exit(1)
            # 分区拓扑数据预加载
            # if USE_CACHE_AFTER_LOAD:
            #     try:
            #         # 获取所有分区名称
            #         zones = _get_all_zone_names()   
            #         if zones:
            #             for zone in zones:
            #                 get_cached_zone_topology(zone)  # 触发加载并缓存
            #             print(f"[缓存] 分区拓扑（共 {len(zones)} 个）加载完成")
            #         else:
            #             print("[缓存] 未找到任何分区，分区拓扑预加载跳过")
            #     except Exception as e:
            #         print(f"[错误] 分区拓扑预加载失败: {e}")
            #         sys.exit(1)
            print("[Info] 所有数据缓存预加载成功")
            print(f"[Info]NetAssist应用启动完成，访问地址：http://{host}:{port}") 
            # print(f"=== Flask应用启动完成，访问地址：https://{host}:{port} ===") 

    else:
        print("[策略] 预加载已关闭，调试模式下数据按需加载")
        print("[调试] DEBUG 日志已开启")
        print(f"[Info]NetAssist应用启动完成，访问地址：http://{host}:{port}") 
        # print(f"[Info]NetAssist应用启动完成，访问地址：https://{host}:{port}") 

# 启动应用
if __name__ == '__main__':

    PRELOAD_ON_STARTUP = False
    USE_CACHE_AFTER_LOAD = False
    # PRELOAD_ON_STARTUP = True
    # USE_CACHE_AFTER_LOAD = True
    # print(f"[策略] 预加载={PRELOAD_ON_STARTUP}, 是否使用缓存={USE_CACHE_AFTER_LOAD}")

    print("[Info] NetAssist应用开始启动")

    # 端口预检 (热重载与端口手工预检冲突，需要2选1注释)
    is_used, msg = check_port_in_use(host, port)
    if is_used:
        logging.error(f"\n错误：端口 {port} 正在被其他程序使用 ({msg})")
        logging.error("请关闭相关程序后重试。\n")
        sys.exit(1)

    initialize_cache()  # 先初始化缓存

    # Waitress 生产服务器启动
    serve(app,
        host=host, 
        port=port,
        threads=4,
        # ssl_context=('cert.pem', 'key.pem'),  # 启用HTTPS 
        )
    # Werkzeug 开发服务器启动
    # app.run(
    #     host=host, 
    #     port=port,
    #     # ssl_context=('cert.pem', 'key.pem'),  # 启用HTTPS 
    #     debug=True,   # 调试模式
    #     # use_reloader=False  # 热重载  (热重载与端口手工预检冲突，需要2选1注释)
    #     )
