#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
脚本功能：从 Excel 表格中读取防火墙（FW）与对端设备（CE）的互联配置，
生成华为防火墙（F系列/E系列）和对端交换机（CE）的命令行脚本。
支持多虚墙（VSYS）、多接口、VRRP、VRF、安全策略、路由、前缀列表等。

工作流程：
1. 解析 Excel 文件，提取每三行一组的连接信息（Active、Standby、VRID）。
2. 生成主用防火墙（Active）的完整配置：接口、VRRP、VSYS、Zone、路由、安全策略。
3. 生成备用防火墙（Standby）的配置（接口 IP 和 VRRP standby）。
4. 按 CE 设备分组，为每台交换机生成配置：VLAN、VRF、Vlanif、Trunk、前缀列表、静态路由。
5. 输出到 output/ 目录下的各自设备命名的 .txt 文件。
"""

import openpyxl
import re
import os
import json
import ipaddress
from collections import defaultdict, OrderedDict

# ======================== 用户自定义配置 ========================
# Excel 文件路径（可修改为实际文件名）
FILE_PATH = "excel_FW脚本批量生成v1.9_虚墙场景.xlsx"
# Excel 工作表名称（根据实际选择 F 系列或 E 系列）
SHEET_NAME = "E系列_每虚墙多接口_支持双向"
# 输出脚本的目录
OUTPUT_DIR = "output"
# 设备名称映射配置文件（JSON格式），存储设备AS号、VRF子接口号等
GLOBAL_DEVICE_INFO = "设备名称映射表.json"
ROLLBACK_DIR = os.path.join(OUTPUT_DIR, "回退脚本")
# 防火墙互联接口使用的子网掩码（固定 /29）
MASK = "255.255.255.248"
# 对端交换机 Vlanif 接口的 MAC 地址（固定值）
MAC_ADDR = "0000-005e-010f"
# 默认 VRRP VRID
DEFAULT_VRID = 2
# 内置 zone 名称集合（这些 zone 无需设置优先级）
BUILTIN_ZONES = {"untrust", "trust", "local", "dmz"}
# 自定义 zone 默认起始优先级（无自定义时从该值递减）
# DEFAULT_ZONE_PRIORITY = 80
# 默认 AS 号（当设备未在映射表中定义时使用）
DEFAULT_AS = 666
# 默认 VRF subint 值（当 VRF 未在映射表中定义时使用）
DEFAULT_VRF_SUBINT = 999
# vlan batch 命令每行最多包含的 VLAN 参数组（用于分行）
MAX_GROUPS_PER_LINE = 10
# ======================== Excel 列名映射 ========================
# 定义 Excel 中各列标题与内部键名的对应关系
COLUMN_MAP = {
    "remote_name": "CE侧设备名",          # 对端设备名称（可能包含多台，用&分隔）
    "remote_ip": "CE侧互联地址",          # 对端互联 IP
    "remote_int": "CE侧互联接口",          # 对端互联接口（如 GigabitEthernet0/0/1）
    "remote_vrf": "CE侧接口VRF",          # 对端接口所属 VRF 实例
    "remote_aggregate": "CE侧聚合组",     # 对端聚合接口（如 Eth-Trunk1）

    "role": "FW主备状态",                 # 防火墙角色：active / standby / vrid等
    "fw_device": "FW设备名",              # 防火墙设备名称
    "fw_vrrp": "FW-VRRP地址",             # VRRP 虚拟 IP 地址
    "fw_int": "FW互联接口",               # 防火墙互联接口（如 GigabitEthernet0/0/1.100）
    "zone": "FW接口所属zone",             # 防火墙接口所属安全区域
    "zone_priority": "zone优先级",        # 自定义 zone 的优先级
    "vsys": "FW接口所属虚墙",             # 虚拟系统名称
    "routes": "业务静态路由",             # 该连接对应的业务路由（如 10.0.0.0/24）
    "prefix_list_name": "前缀列表名称",   # 前缀列表名称（用于路由过滤）
}

# 用于记录已警告过的设备和VRF，避免重复输出警告信息
_warned_devices = set()
_warned_vrfs = set()
# ================== 配置模板 ==================
# 系统级固定命令
SYSTEM_TEMPLATE = "system"           # 进入系统视图
RETURN_TEMPLATE = "return"           # 返回用户视图
COMMIT_TEMPLATE = "commit"           # 提交配置

# 接口子接口 VLAN 终结命令（F系列采用 dot1q termination vid）
F_DOT1Q_TEMPLATE = " dot1q termination vid {vlan_id}\n"
# 接口子接口 VLAN 终结命令（E系列采用 vlan-type dot1q）
E_DOT1Q_TEMPLATE = " vlan-type dot1q {vlan_id}\n"

# 防火墙接口配置模板（Active 状态，不含 VRRP）
FW_INTF_ACTIVE_TEMPLATE = """
interface {intf}
 description {desc}
{dot1q}
 ip address {ip} {mask}
{service_manage}
#"""

# VRRP 配置模板（Active 状态）
FW_VRRP_ACTIVE_TEMPLATE = """
interface {intf}
 vrrp vrid {vrid} virtual-ip {vip} active
#"""

# 防火墙接口配置模板（Standby 状态，含 VRRP standby）
FW_INTF_STANDBY_TEMPLATE = """interface {intf}
 description {desc}
 ip address {ip} {mask}
 vrrp vrid {vrid} virtual-ip {vip} standby
#"""

# VSYS 相关模板
VSYS_NAME_TEMPLATE = "vsys name {vsys}"           # 创建虚拟系统
VSYS_ASSIGN_TEMPLATE = " assign interface {intf}" # 将接口分配给 VSYS

# Zone 配置模板（内置 zone 无优先级）
ZONE_BUILTIN_TEMPLATE = """
firewall zone {zone}
{add_interfaces}
#"""
# Zone 配置模板（自定义 zone 需设置优先级）
ZONE_CUSTOM_TEMPLATE = """
firewall zone name {zone}
{priority_line}
{add_interfaces}
#"""

# 安全策略模板（固定放行 ICMP）
SECURITY_POLICY_TEMPLATE = """
security-policy
 rule name ICMP
  service icmp
  action permit
#"""

# 路由模板（普通路由）
ROUTE_TEMPLATE = "ip route-static {dest} {mask} {nh} description {desc}"
# 路由模板（VPN实例路由）
ROUTE_VPN_TEMPLATE = "ip route-static vpn-instance {vrf} 0.0.0.0 0.0.0.0 {nh} description {desc}"

# 前缀列表模板
PREFIX_LIST_TEMPLATE = "ip ip-prefix {pl_name} permit {dest} {prefixlen}"

# 交换机侧 VRF 配置模板
VRF_TEMPLATE = """
ip vpn-instance {vrf}
 ipv4-family
  route-distinguisher {rd}
#"""

# Vlanif 接口模板（含可选的 VPN 绑定）
VLANIF_TEMPLATE = """
interface {vlanif}
 description {desc}
{binding}
 ip address {ip} {mask}
 mac-address {mac}
#"""

# Trunk 接口模板
TRUNK_TEMPLATE = """
interface {intf}
 port trunk allow-pass vlan {vlan}
#"""

# VLAN batch 命令前缀（实际内容由 split_vlan_batch 动态生成）
VLAN_BATCH_PREFIX = "vlan batch"


def get_rd(device, vrf):
    """
    根据设备名和 VRF 名计算 RD（路由标识符）值，格式为 AS:subint。
    若设备或 VRF 未在映射表中，则使用默认值并输出警告。
    """
    if not vrf:
        return ""
    info = DEVICE_MAP.get(device)
    if info is None:
        if device not in _warned_devices:
            print(f"警告：设备 '{device}' 未在 DEVICE_MAP 中定义，使用默认 AS {DEFAULT_AS}")
            _warned_devices.add(device)
        as_num = DEFAULT_AS
    else:
        as_num = info["as"]
    
    subint = VRF_SUBINT_MAP.get(vrf)
    if subint is None:
        if vrf not in _warned_vrfs:
            print(f"警告：VRF '{vrf}' 未在 VRF_SUBINT_MAP 中定义，使用默认 subint {DEFAULT_VRF_SUBINT}")
            _warned_vrfs.add(vrf)
        subint = DEFAULT_VRF_SUBINT
    
    return f"{as_num}:{subint}"

# ======================== 辅助函数 ========================
def remove_empty_lines(text):
    """去除配置文本中的所有空行（仅包含空白字符的行）"""
    lines = text.splitlines()
    non_empty_lines = [line for line in lines if line.strip() != ""]
    return "\n".join(non_empty_lines)

def normalize_ip(ip_str):
    """
    标准化 IP 地址字符串：如果包含 /CIDR 掩码，则提取 IP 部分并给出警告，
    因为掩码由其他字段单独管理。
    """
    if not ip_str:
        return ip_str
    ip_str = str(ip_str).strip()
    if '/' in ip_str:
        parts = ip_str.split('/', 1)
        ip = parts[0].strip()
        # mask_len 仅用于提醒，不实际使用
        mask_len = parts[1].strip() if len(parts) > 1 else ''
        print(f"警告：IP地址 '{ip_str}' 包含CIDR掩码，已自动提取IP '{ip}'，掩码部分被忽略。请检查Excel中的IP格式。")
        return ip
    return ip_str

def prefix_to_mask(prefix):
    """将 CIDR 前缀长度（如 24）转换为点分十进制掩码（如 255.255.255.0）"""
    net = ipaddress.IPv4Network(f"0.0.0.0/{prefix}", strict=False)
    return str(net.netmask)

def parse_route(route_str):
    """
    解析路由字符串，支持两种格式：
    - 带CIDR：如 "10.0.0.0/24" → 返回 ("10.0.0.0", "255.255.255.0")
    - 不带掩码：如 "192.168.1.1" → 返回 ("192.168.1.1", "255.255.255.255")
    """
    if '/' in route_str:
        dest, prefix = route_str.split('/')
        mask = prefix_to_mask(int(prefix))
    else:
        dest = route_str
        mask = "255.255.255.255"
    return dest, mask

def split_device_names(name_str):
    """
    将设备名字符串拆分为列表，支持换行或 '&' 分隔。
    例如 "FW1&FW2" 或 "FW1\nFW2" 均返回 ["FW1", "FW2"]。
    """
    if not name_str:
        return []
    # 先按换行符分割
    parts = re.split(r'[\n\r]+', name_str)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        return parts
    # 如果只有一行，再按 & 分割
    if '&' in name_str:
        return [p.strip() for p in name_str.split('&') if p.strip()]
    return [name_str.strip()]

def format_cluster_name(name_str):
    """
    将设备名称格式化为“前缀+编号1&编号2”的紧凑形式，用于描述。
    例如 "TEST-DXCORE-W01&TEST-DXCORE-W02" → "TEST-DXCORE-W01&W02"
    若只有一个设备，则直接返回该名称。
    """
    devices = split_device_names(name_str)
    if len(devices) == 1:
        return devices[0]
    first, second = devices[0], devices[1]
    # 提取末尾的数字部分
    m1 = re.search(r'(\d+)$', first)
    m2 = re.search(r'(\d+)$', second)
    if m1 and m2:
        prefix = first[:first.rfind(m1.group(1))]
        return f"{prefix}{m1.group(1)}&{m2.group(1)}"
    return f"{first}&{second}"

def sort_naturally(items):
    """
    对字符串列表进行自然排序（数字按数值大小，字母按字典序）。
    例如 ["int1", "int10", "int2"] → ["int1", "int2", "int10"]
    """
    def key_func(s):
        # 将字符串拆分为数字和非数字部分，数字部分转换为整数以便数值排序
        return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', s)]
    return sorted(items, key=key_func)

def sort_routes_by_dest(routes):
    """
    对路由列表按目的地址的 IP 数值进行排序。
    每条路由为元组 (dest, mask, nh, desc)
    """
    def route_key(route):
        dest, mask, nh, desc = route
        return ipaddress.IPv4Address(dest)
    return sorted(routes, key=route_key)

def parse_ce_interface(intf_str):
    """
    解析 CE 设备接口字符串，返回 (接口名, VLAN ID) 或 (接口名, None)。
    支持：
    - 子接口：GigabitEthernet0/0/1.100 → ("GigabitEthernet0/0/1", 100)
    - Vlanif：Vlanif100 → ("Vlanif100", 100)
    - 普通接口：GigabitEthernet0/0/1 → ("GigabitEthernet0/0/1", None)
    """
    if not intf_str:
        return None, None
    intf_str = intf_str.strip()
    # 子接口格式：接口.编号
    if '.' in intf_str:
        parts = intf_str.split('.')
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0], int(parts[1])
    # Vlanif 格式
    if intf_str.lower().startswith('vlanif'):
        num_part = intf_str[6:]
        if num_part.isdigit():
            return f"Vlanif{num_part}", int(num_part)
    return intf_str, None

def split_ce_interfaces(text):
    """将多行接口文本（以 <br> 或换行分隔）拆分为列表，去除空串"""
    if not text:
        return []
    parts = re.split(r'<br>|\n|\r\n', text)
    return [p.strip() for p in parts if p.strip()]

def format_remote_aggregate_for_desc(remote_aggregate_str):
    """
    将对端接口字符串格式化为用于 description 的简洁形式。
    如果多个接口前缀相同且编号连续，则合并显示。
    例如 "GigabitEthernet0/0/1<br>GigabitEthernet0/0/2" → "GigabitEthernet0/0/1&2"
    """
    if not remote_aggregate_str:
        return ""
    parts = re.split(r'<br>|\n|\r\n', remote_aggregate_str)
    clean_parts = [p.strip() for p in parts if p.strip()]
    if not clean_parts:
        return ""
    parsed = []
    for p in clean_parts:
        # 匹配前缀（非数字）+ 数字结尾
        m = re.match(r'^([^\d]+)(\d+)$', p)
        if m:
            prefix, num = m.groups()
            parsed.append((prefix, num))
        else:
            parsed.append((p, None))
    # 检查是否所有接口都有相同的前缀
    prefixes = [p[0] for p in parsed if p[1] is not None]
    if len(prefixes) == len(parsed) and len(set(prefixes)) == 1:
        result = [f"{prefixes[0]}{parsed[0][1]}"]
        for _, num in parsed[1:]:
            result.append(num)
        return "&".join(result)
    else:
        return "&".join(clean_parts)

def compress_vlan_to_ranges(vlan_set):
    """
    将 VLAN 编号集合转换为区间列表，例如 {1,2,3,5,6} → ["1 to 3", "5 to 6"]
    """
    if not vlan_set:
        return []
    vlans = sorted(vlan_set)
    ranges = []
    start = vlans[0]
    end = vlans[0]
    for v in vlans[1:]:
        if v == end + 1:
            end = v
        else:
            ranges.append(str(start) if start == end else f"{start} to {end}")
            start = end = v
    ranges.append(str(start) if start == end else f"{start} to {end}")
    return ranges

def format_vlan_list(vlan_set):
    """将 VLAN 集合格式化为空格分隔的区间字符串，用于 port trunk allow-pass vlan"""
    ranges = compress_vlan_to_ranges(vlan_set)
    return " ".join(ranges)

def split_vlan_batch(vlan_set, max_params):
    """
    将 VLAN 集合拆分为多条 vlan batch 命令，每条命令最多包含 max_params 个参数组。
    参数组可以是单个 VLAN 或区间。
    """
    ranges = compress_vlan_to_ranges(vlan_set)
    if not ranges:
        return []
    commands = []
    for i in range(0, len(ranges), max_params):
        chunk = ranges[i:i+max_params]
        commands.append(f"{VLAN_BATCH_PREFIX} {' '.join(chunk)}")
    return commands

# ======================== 解析Excel ========================
def parse_excel(file_path, sheet_name):
    """
    解析 Excel 文件，提取所有连接信息。
    返回一个列表，每个元素是一个字典，包含单个连接（每3行一组）的完整配置。
    注意：Excel 中每三行为一组（Active、Standby、VRID/其他），脚本会合并这些行。
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb[sheet_name]

    # 读取表头，建立列名到索引的映射
    header = [cell.value for cell in ws[1]]
    col_idx = {}
    for key, title in COLUMN_MAP.items():
        if title in header:
            col_idx[key] = header.index(title)
        else:
            col_idx[key] = None

    # 读取数据行（从第2行开始）
    rows = []
    for row in range(2, ws.max_row + 1):
        row_data = [ws.cell(row, col).value for col in range(1, ws.max_column + 1)]
        if any(v is not None for v in row_data):
            rows.append(row_data)

    firewall_connections = []
    lb_connections = []
    # 上下文变量，用于跨行积累信息（如 vsys 可能只在一行中填写）
    ctx = {
        "remote_name": None,
        "remote_ip": None,
        "remote_vrf": None,
        "fw_int": None,
        "zone": None,
        "vsys": None,
        "routes": [],
    }

    i = 0
    while i < len(rows):
        row = rows[i]

        # 更新上下文中的 vsys（如果当前行有值）
        vsys_col = col_idx.get("vsys")
        if vsys_col is not None:
            vsys_val = row[vsys_col]
            if vsys_val and "负载" in str(vsys_val):
                # 负载连接（单行）
                lb_conn = {}
                for key in ["remote_name", "remote_vrf", "remote_int", "remote_ip",
                            "remote_aggregate", "fw_device", "fw_vrrp", "routes", "vsys"]:
                    col = col_idx.get(key)
                    if col is not None:
                        val = row[col]
                        if val is not None:
                            lb_conn[key] = str(val).strip()
                        else:
                            lb_conn[key] = None
                if lb_conn.get("remote_ip"):
                    lb_conn["remote_ip"] = normalize_ip(lb_conn["remote_ip"])
                if lb_conn.get("routes"):
                    routes_raw = lb_conn["routes"]
                    if isinstance(routes_raw, str):
                        routes = [r.strip() for r in re.split(r'<br>|\n', routes_raw) if r.strip()]
                    else:
                        routes = [str(routes_raw).strip()]
                    lb_conn["routes"] = routes
                else:
                    lb_conn["routes"] = []
                if lb_conn.get("remote_int"):
                    intf, vlan = parse_ce_interface(lb_conn["remote_int"])
                    lb_conn["ce_vlan"] = vlan
                    lb_conn["ce_intf"] = intf
                else:
                    lb_conn["ce_vlan"] = None
                    lb_conn["ce_intf"] = None
                if lb_conn.get("remote_aggregate"):
                    intfs = split_ce_interfaces(lb_conn["remote_aggregate"])
                    lb_conn["ce_aggregate_list"] = [i.strip() for i in intfs if i.strip()]
                else:
                    lb_conn["ce_aggregate_list"] = []
                lb_conn["next_hop"] = lb_conn.get("fw_vrrp")
                lb_connections.append(lb_conn)
                i += 1
                continue

        # 防火墙连接（三行一组）
        if vsys_col is not None:
            val = row[vsys_col]
            if val is not None and str(val).strip():
                # 将横杆替换为下划线，因为防火墙配置中通常使用下划线
                ctx["vsys"] = str(val).strip().replace('-', '_')

        # 检查 role 列，只有 role 为 "active" 的行才触发新连接创建
        role_col = col_idx.get("role")
        role = row[role_col] if role_col is not None else None
        if role and str(role).strip().lower() == "active":
            # 从当前行提取基础信息（remote_name, remote_ip, remote_vrf, fw_int, zone）
            for key in ["remote_name", "remote_ip", "remote_vrf", "fw_int", "zone"]:
                col = col_idx.get(key)
                if col is not None:
                    val = row[col]
                    if val is not None and str(val).strip():
                        raw = str(val).strip()
                        if key in ("zone",):
                            raw = raw.replace('-', '_')
                        if key == "remote_ip":
                            raw = normalize_ip(raw)
                        ctx[key] = raw
                    else:
                        ctx[key] = None

            # 提取业务路由
            routes_col = col_idx.get("routes")
            if routes_col is not None:
                routes_raw = row[routes_col]
                if routes_raw is not None and str(routes_raw).strip():
                    if isinstance(routes_raw, str):
                        routes = [r.strip() for r in re.split(r'<br>|\n', routes_raw) if r.strip()]
                    else:
                        routes = [str(routes_raw).strip()]
                    ctx["routes"] = routes
                else:
                    ctx["routes"] = []

            # 提取前缀列表名称
            prefix_list_raw = row[col_idx.get("prefix_list_name")] if col_idx.get("prefix_list_name") is not None else None
            prefix_list_name = str(prefix_list_raw).strip() if prefix_list_raw else None

            # 提取 zone 优先级
            zone_priority_raw = row[col_idx.get("zone_priority")] if col_idx.get("zone_priority") is not None else None
            zone_priority = str(zone_priority_raw).strip() if zone_priority_raw is not None else None

            # 提取 fw_device, fw_vrrp, remote_int, remote_aggregate
            fw_device_col = col_idx.get("fw_device")
            fw_vrrp_col = col_idx.get("fw_vrrp")
            remote_int_col = col_idx.get("remote_int")
            remote_aggregate_col = col_idx.get("remote_aggregate")

            fw_device = row[fw_device_col] if fw_device_col is not None else None
            fw_ip = row[fw_vrrp_col] if fw_vrrp_col is not None else None
            
            remote_int_val = row[remote_int_col] if remote_int_col is not None else None
            remote_aggregate_val = row[remote_aggregate_col] if remote_aggregate_col is not None else None

            # 构建连接字典（包含本行及后续两行的数据）
            conn = {
                "remote_name": ctx["remote_name"],
                "remote_ip": ctx["remote_ip"],
                "remote_vrf": ctx["remote_vrf"],
                "fw_int": ctx["fw_int"],
                "zone": ctx["zone"],
                "vsys": ctx["vsys"],
                "routes": ctx["routes"].copy(),
                "role1": str(role).strip(),
                "fw_device1": str(fw_device).strip() if fw_device else "",
                "fw_ip1": normalize_ip(str(fw_ip).strip()) if fw_ip else "",
                "remote_int": str(remote_int_val).strip() if remote_int_val else "",
                "remote_aggregate": str(remote_aggregate_val).strip() if remote_aggregate_val else "",
                "role2": None, "fw_device2": None, "fw_ip2": None, 
                "role3": None, "fw_device3": None, "fw_ip3": None, 
                "zone_priority": zone_priority,
                "prefix_list_name": prefix_list_name,
                
            }
            
            # 读取后续两行（第2行、第3行）分别填充 role2/fw_device2等 和 role3/fw_device3等
            # i 是当前行索引，j 是偏移量，从1开始，range取值为1,2
            for j in range(1, 3):
                if i + j < len(rows):
                    nr = rows[i+j]
                    r = nr[role_col] if role_col is not None else None
                    fd = nr[fw_device_col] if fw_device_col is not None else None
                    fi = nr[fw_vrrp_col] if fw_vrrp_col is not None else None
                    if j == 1:
                        conn["role2"] = str(r).strip() if r else ""
                        conn["fw_device2"] = str(fd).strip() if fd else ""
                        conn["fw_ip2"] = normalize_ip(str(fi).strip()) if fi else ""
                    else:
                        conn["role3"] = str(r).strip() if r else ""
                        conn["fw_device3"] = str(fd).strip() if fd else ""
                        conn["fw_ip3"] = normalize_ip(str(fi).strip()) if fi else ""


            # 处理 CE 接口列表（合并 remote_aggregate 中的所有接口，去重）
            intf_list = split_ce_interfaces(conn["remote_aggregate"])
            all_intfs = list(dict.fromkeys(intf_list))
            conn["ce_intf_list"] = all_intfs
            # 解析 remote_int 提取 VLAN ID（用于 Vlanif）
            _, ce_vlan = parse_ce_interface(conn["remote_int"])
            conn["ce_vlan"] = ce_vlan
            
            # 从 role3 中提取 VRRP VRID（格式如 "vrid 2"）
            # 如果 role3 为空，使用默认值
            vrid_match = re.search(r'vrid\s+(\d+)', conn["role3"] or "", re.I)
            conn["vrid"] = int(vrid_match.group(1)) if vrid_match else DEFAULT_VRID

            # 从 fw_int 中提取 VLAN ID（子接口编号）
            if conn["fw_int"]:
                m = re.search(r'\.(\d+)$', conn["fw_int"])
                conn["vlan_id"] = int(m.group(1)) if m else None
            else:
                conn["vlan_id"] = None

            firewall_connections.append(conn)
            i += 3
        else:
            i += 1
            print(f"跳过非 Active 行，当前第 {i+1} 行的 role 值为: {role}")

    return firewall_connections, lb_connections

# ======================== 生成配置 ========================
def generate_fw_active(connections, device_name, sheet_name,):
    """
    生成主用防火墙（Active）的配置脚本。
    包括：接口、VRRP、VSYS、Zone、路由、安全策略等。
    device_name: 当前防火墙设备名称（用于命令中的提示）
    """
    lines = []
    lines.append(device_name)
    lines.append("\n\n#")
    lines.append(SYSTEM_TEMPLATE)

    # 收集所有防火墙接口，并提前创建空接口（仅 interface 命令）
    all_ints = sort_naturally({c["fw_int"] for c in connections if c["fw_int"]})
    for intf in all_ints:
        lines.append(f"interface {intf}")
    lines.append("#")

    # 分配接口到 VSYS
    vsys_map = defaultdict(set)
    for c in connections:
        if c["vsys"] and c["fw_int"]:
            vsys_map[c["vsys"]].add(c["fw_int"])
    for vsys in sort_naturally(vsys_map.keys()):
        lines.append(VSYS_NAME_TEMPLATE.format(vsys=vsys))
        for intf in sort_naturally(vsys_map[vsys]):
            lines.append(VSYS_ASSIGN_TEMPLATE.format(intf=intf))
        lines.append("#")

    # 为每个接口配置 IP、描述、子接口（dot1q）和 service-manage
    for intf in all_ints:
        conn = next(c for c in connections if c["fw_int"] == intf)
        remote_cluster = format_cluster_name(conn['remote_name'])
        remote_aggregate_desc = format_remote_aggregate_for_desc(conn['remote_aggregate'])
        desc = f"to {remote_cluster} {remote_aggregate_desc} {conn['vsys']}_zone_{conn['zone']}"
        dot1q = ""
        if conn["vlan_id"] is not None:
            # 根据工作表名称判断设备系列（F系列或E系列），选用不同子接口命令
            if "F" in sheet_name:
                dot1q = F_DOT1Q_TEMPLATE.format(vlan_id=conn["vlan_id"])
            elif "E" in sheet_name:
                dot1q = E_DOT1Q_TEMPLATE.format(vlan_id=conn["vlan_id"])
            else:
                # 默认使用F系列命令
                dot1q = F_DOT1Q_TEMPLATE.format(vlan_id=conn["vlan_id"])
        # F系列需要关闭 service-manage，E系列根墙下不配置（后续在vsys内配置）
        if "F" in sheet_name:
            service_manage = " undo service-manage enable\n"
        else:
            service_manage = ""  # E系列根墙下不配置
        lines.append(FW_INTF_ACTIVE_TEMPLATE.format(
            intf=intf,
            desc=desc,
            dot1q=dot1q,
            ip=conn['fw_ip1'],
            mask=MASK,
            service_manage=service_manage
        ))

    # 配置 VRRP（active）
    for intf in all_ints:
        conn = next(c for c in connections if c["fw_int"] == intf)
        lines.append(FW_VRRP_ACTIVE_TEMPLATE.format(
            intf=intf,
            vrid=conn['vrid'],
            vip=conn['fw_ip3']
        ))

    # 按 VSYS 分组处理 zone、路由、安全策略等
    vsys_groups = defaultdict(lambda: {"connections": [], "custom_zones": []})
    for c in connections:
        if c["vsys"]:
            vsys_groups[c["vsys"]]["connections"].append(c)
            zone = c["zone"]
            if zone and zone.lower() not in BUILTIN_ZONES and zone not in vsys_groups[c["vsys"]]["custom_zones"]:
                vsys_groups[c["vsys"]]["custom_zones"].append(zone)

    vsys_list = sort_naturally(vsys_groups.keys())
    for idx, vsys in enumerate(vsys_list):
        # 切换至对应 VSYS 上下文
        if idx == 0:
            lines.append(f"switch vsys {vsys}")
            lines.append(SYSTEM_TEMPLATE)
            lines.append("#")
        else:
            lines.append(RETURN_TEMPLATE)
            lines.append("#")
            lines.append(SYSTEM_TEMPLATE)
            lines.append(f"switch vsys {vsys}")
            lines.append(SYSTEM_TEMPLATE)
            lines.append("#")

        # 对于 E 系列，在 VSYS 内对接口关闭 service-manage
        if "E" in sheet_name:
            vsys_conns = vsys_groups[vsys]["connections"]
            vsys_ints = {c["fw_int"] for c in vsys_conns if c["fw_int"]}
            for intf in sort_naturally(vsys_ints):
                lines.append(f"interface {intf}")
                lines.append(" undo service-manage enable")
                lines.append("#")   # 分隔

        # 收集该 VSYS 内的所有路由，去重并排序
        vsys_conns = vsys_groups[vsys]["connections"]
        vsys_routes = []
        for c in vsys_conns:
            next_hop = c["remote_ip"]
            for route in c["routes"]:
                if not route:
                    continue
                dest, mask = parse_route(route)
                vsys_routes.append((dest, mask, next_hop, f"FW_{c['vsys']}_zone_{c['zone']}"))

        # 去重（基于目的、掩码、下一跳）
        unique_routes = {}
        for dest, mask, nh, desc in vsys_routes:
            key = (dest, mask, nh)
            if key not in unique_routes:
                unique_routes[key] = (dest, mask, nh, desc)
        vsys_routes = list(unique_routes.values())
        vsys_routes = sort_routes_by_dest(vsys_routes)
        # 将默认路由（0.0.0.0/0）排在最前面
        default_routes = [r for r in vsys_routes if r[0] == "0.0.0.0" and r[1] == "0.0.0.0"]
        other_routes = [r for r in vsys_routes if not (r[0] == "0.0.0.0" and r[1] == "0.0.0.0")]
        all_sorted = default_routes + other_routes

        if all_sorted:
            for dest, mask, nh, desc in all_sorted:
                lines.append(ROUTE_TEMPLATE.format(dest=dest, mask=mask, nh=nh, desc=desc))
            lines.append("#")

        # 按 zone 归类接口
        zone_ints = defaultdict(set)
        for c in vsys_conns:
            if c["zone"] and c["fw_int"]:
                zone_ints[c["zone"]].add(c["fw_int"])

        # 配置内置 zone（无优先级）
        builtin_zones_present = [z for z in zone_ints if z.lower() in BUILTIN_ZONES]
        for zone in sort_naturally(builtin_zones_present):
            ints = sort_naturally(zone_ints[zone])
            if not ints:
                continue
            add_intf_lines = "\n".join(f" add interface {i}" for i in ints)
            lines.append(ZONE_BUILTIN_TEMPLATE.format(zone=zone, add_interfaces=add_intf_lines))

        # 配置自定义 zone（需优先级）
        custom_zones = vsys_groups[vsys]["custom_zones"]
        # 从连接中提取用户指定的优先级（如果未指定则使用默认递减）
        zone_priority_map = {}
        for c in vsys_conns:
            z = c.get("zone")
            if z and z.lower() not in BUILTIN_ZONES:
                pri = c.get("zone_priority")
                if pri is not None and z not in zone_priority_map:
                    zone_priority_map[z] = pri
        
        for zone in custom_zones:
            ints = sort_naturally(zone_ints.get(zone, []))
            if not ints:
                continue
            custom_pri = zone_priority_map.get(zone)
            add_intf_lines = "\n".join(f" add interface {i}" for i in ints)
            if custom_pri is not None:
                priority_line = f" set priority {custom_pri}"
            else:
                priority_line = ""
            lines.append(ZONE_CUSTOM_TEMPLATE.format(
                zone=zone,
                priority_line=priority_line,
                add_interfaces=add_intf_lines
            ))

        # 如果有接口属于 public VRF，则放行 ICMP 安全策略
        has_public_interface = any(
            c["fw_int"] and c["remote_vrf"] and c["remote_vrf"].lower() in PUBLIC_VRF_KEYWORDS
            for c in vsys_conns
        )
        if has_public_interface:
            lines.append(SECURITY_POLICY_TEMPLATE)

    lines.append(RETURN_TEMPLATE)
    lines.append("#")
    return "\n".join(lines)

def generate_fw_standby(connections, device_name):
    """
    生成备用防火墙（Standby）的配置脚本。
    备用防火墙仅需配置接口 IP 和 VRRP standby。
    """
    lines = []
    lines.append(device_name)
    lines.append("\n\n#")
    lines.append(SYSTEM_TEMPLATE)
    lines.append("#")

    all_ints = sort_naturally({c["fw_int"] for c in connections if c["fw_int"]})
    for intf in all_ints:
        conn = next(c for c in connections if c["fw_int"] == intf)
        remote_cluster = format_cluster_name(conn['remote_name'])
        remote_aggregate_desc = format_remote_aggregate_for_desc(conn['remote_aggregate'])
        desc = f"to {remote_cluster} {remote_aggregate_desc} {conn['vsys']}_zone_{conn['zone']}"

        lines.append(FW_INTF_STANDBY_TEMPLATE.format(
            intf=intf,
            desc=desc,
            ip=conn['fw_ip2'],
            mask=MASK,
            vrid=conn['vrid'],
            vip=conn['fw_ip3']
        ))

    lines.append(RETURN_TEMPLATE)
    lines.append("#")
    return "\n".join(lines)

# ======================== 生成交换机侧配置（融合防火墙+负载） ========================
def generate_peer_device(peer_connections, all_connections, device_name, lb_connections=None):
    """
    生成对端 CE 设备的配置脚本，融合防火墙和负载数据。
    参数：
        peer_connections: 属于该设备的防火墙连接列表
        all_connections: 全部防火墙连接（用于跨设备路由）
        device_name: 当前CE设备名
        lb_connections: 属于该设备的负载连接列表（可选，默认None）
    """
    lines = []
    lines.append(device_name)
    lines.append("\n\n#")
    lines.append(SYSTEM_TEMPLATE)
    lines.append("#")

    all_vlans = set()
    ce_intf_vlans = defaultdict(set)   # 聚合接口 -> VLAN集合
    vrf_order = OrderedDict()          # 需要创建的VRF（仅防火墙）

    # 处理防火墙连接
    for c in peer_connections:
        vlan = c.get("ce_vlan")
        if vlan is not None:
            all_vlans.add(vlan)
            remote_aggregate_str = c.get("remote_aggregate", "")
            if remote_aggregate_str:
                intfs = re.split(r'<br>|\n|\r\n', remote_aggregate_str)
                intfs = [i.strip() for i in intfs if i.strip()]
                for intf in intfs:
                    ce_intf_vlans[intf].add(vlan)
        vrf = c["remote_vrf"]
        if vrf and vrf.lower() not in PUBLIC_VRF_KEYWORDS and vrf not in vrf_order:
            vrf_order[vrf] = None

    # 处理负载连接（独立逻辑，不创建VRF）
    lb_vlan_to_conn = {}  # 用于后续生成Vlanif
    if lb_connections:
        for lb in lb_connections:
            vlan = lb.get("ce_vlan")
            if vlan is not None:
                all_vlans.add(vlan)
                # 聚合接口
                agg_list = lb.get("ce_aggregate_list", [])
                for intf in agg_list:
                    ce_intf_vlans[intf].add(vlan)
                lb_vlan_to_conn[vlan] = lb

    # 生成 vlan batch 命令（每行最多 MAX_GROUPS_PER_LINE 个参数组）
    max_params = MAX_GROUPS_PER_LINE
    vlan_cmds = split_vlan_batch(all_vlans, max_params)
    if vlan_cmds:
        lines.extend(vlan_cmds)
        lines.append("#")

    # 创建 VRF 实例
    for vrf in vrf_order.keys():
        try:
            rd = get_rd(device_name, vrf)
        except ValueError as e:
            print(f"错误：{e}，跳过 VRF '{vrf}' 配置")
            continue
        lines.append(VRF_TEMPLATE.format(vrf=vrf, rd=rd))

    # ---- 生成 Vlanif 接口（防火墙侧） ----
    vlan_to_conn = {}
    for c in peer_connections:
        vlan = c.get("ce_vlan")
        if vlan is not None and vlan not in vlan_to_conn:
            vlan_to_conn[vlan] = c

    for vlan, conn in vlan_to_conn.items():
        fw1, fw2 = conn["fw_device1"], conn["fw_device2"]
        m1 = re.search(r'(\d+)$', fw1)
        m2 = re.search(r'(\d+)$', fw2)
        if m1 and m2:
            prefix = fw1[:fw1.rfind(m1.group(1))]
            fw_cluster = f"{prefix}{m1.group(1)}&{m2.group(1)}"
        else:
            fw_cluster = f"{fw1}&{fw2}"
        desc = f"to {fw_cluster} {conn['fw_int']} {conn['zone']}"
        vlanif = f"Vlanif{vlan}"
        binding = ""
        # 如果 VRF 不是 public，则绑定 VPN 实例
        if conn["remote_vrf"] and conn["remote_vrf"].lower() not in PUBLIC_VRF_KEYWORDS:
            binding = f" ip binding vpn-instance {conn['remote_vrf']}\n"
        lines.append(VLANIF_TEMPLATE.format(
            vlanif=vlanif,
            desc=desc,
            binding=binding,
            ip=conn['remote_ip'],
            mask=MASK,
            mac=MAC_ADDR
        ))
    # ---- 生成 Vlanif 接口（负载侧） ----
    for vlan, lb in lb_vlan_to_conn.items():
        vrf = lb.get("remote_vrf")
        ip = lb.get("remote_ip")
        if not ip:
            continue
        vlanif = f"Vlanif{vlan}"
        desc = f"to {lb.get('fw_device', 'LB')}"
        binding = ""
        if vrf and vrf.lower() not in PUBLIC_VRF_KEYWORDS:
            binding = f" ip binding vpn-instance {vrf}\n"
        lines.append(VLANIF_TEMPLATE.format(
            vlanif=vlanif,
            desc=desc,
            binding=binding,
            ip=ip,
            mask=MASK,
            mac=MAC_ADDR
        ))

    # 配置 Trunk 接口（允许 VLAN 通过）
    for intf, vlan_set in ce_intf_vlans.items():
        if not vlan_set:
            continue
        vlan_str = format_vlan_list(vlan_set)
        lines.append(TRUNK_TEMPLATE.format(intf=intf, vlan=vlan_str))

    # ---- 前缀列表（仅防火墙） ----
    # 收集所有 VSYS 下的非默认路由
    vsys_detail_routes = defaultdict(set)
    for c in all_connections:
        vsys = c.get("vsys")
        if not vsys:
            continue
        for route in c.get("routes", []):
            if not route or route == "0.0.0.0/0":
                continue
            if '/' in route:
                dest, prefix = route.split('/')
                prefixlen = int(prefix)
            else:
                dest = route
                prefixlen = 32
            vsys_detail_routes[vsys].add((dest, prefixlen))

    prefix_cache = defaultdict(set)  # 前缀列表名 → 路由集合
    for c in peer_connections:
        pl_name = c.get("prefix_list_name")
        if not pl_name:
            continue
        vsys = c.get("vsys")
        if not vsys:
            continue
        routes = vsys_detail_routes.get(vsys, set())
        if routes:
            prefix_cache[pl_name].update(routes)

    # 生成前缀列表（包含 route-policy）
    # 合并同名路由，并标记是否需要 route-policy
    name_groups = {}  # final_name -> {'routes': set(), 'has_route_policy': bool}
    for pl_name, routes_set in prefix_cache.items():
        if "新建" in pl_name:
            clean_name = pl_name.replace("新建", "")
            if not clean_name:
                print(f"警告：前缀列表名称 '{pl_name}' 去除'新建'后为空，已跳过")
                continue
            if clean_name not in name_groups:
                name_groups[clean_name] = {'routes': set(), 'has_route_policy': False}
            name_groups[clean_name]['routes'].update(routes_set)
            name_groups[clean_name]['has_route_policy'] = True
        else:
            if pl_name not in name_groups:
                name_groups[pl_name] = {'routes': set(), 'has_route_policy': False}
            name_groups[pl_name]['routes'].update(routes_set)

    # 先集中输出所有 route-policy（仅对需要 route-policy 的名称）
    for name in sorted(name_groups.keys()):
        group = name_groups[name]
        if group['has_route_policy']:
            lines.append(f"route-policy {name} permit node 10")
            lines.append(f" if-match ip-prefix {name}")
            lines.append("#")
            lines.append(f"route-policy {name} deny node 20")
            lines.append("#")

    # 再集中输出所有 ip-prefix（所有名称）
    for name in sorted(name_groups.keys()):
        group = name_groups[name]
        if not group['routes']:
            continue
        sorted_routes = sorted(group['routes'],
                               key=lambda x: (ipaddress.IPv4Address(x[0]), x[1]))
        for dest, prefixlen in sorted_routes:
            lines.append(PREFIX_LIST_TEMPLATE.format(pl_name=name, dest=dest, prefixlen=prefixlen))
        lines.append("#")

    # ---- 静态路由（防火墙 + 负载） ----
    route_cmds = []

    # 防火墙侧路由（原有逻辑）
    # 如果存在 public VRF 连接，则需为各 VSYS 的详细路由生成指向 FW 的静态路由
    has_public = any(c["remote_vrf"] and c["remote_vrf"].lower() in PUBLIC_VRF_KEYWORDS for c in peer_connections)
    if has_public:
        # 收集 public VRF 下各 VSYS 的 VIP 地址
        vsys_public_vip = {}
        for c in all_connections:
            vsys = c["vsys"]
            if not vsys:
                continue
            vrf = (c["remote_vrf"] or "public").lower()
            if vrf in PUBLIC_VRF_KEYWORDS and c["fw_ip3"]:
                vsys_public_vip[vsys] = c["fw_ip3"]

        # 收集各 VSYS 的非默认路由
        vsys_routes = defaultdict(set)
        for c in all_connections:
            vsys = c["vsys"]
            if not vsys:
                continue
            vrf = (c["remote_vrf"] or "public").lower()
            if vrf not in PUBLIC_VRF_KEYWORDS:
                for route in c["routes"]:
                    if route:
                        vsys_routes[vsys].add(route)

        detail_routes = []
        for vsys, route_set in vsys_routes.items():
            vip = vsys_public_vip.get(vsys)
            if not vip:
                continue
            for route in route_set:
                dest, mask = parse_route(route)
                detail_routes.append((dest, mask, vip, f"FW_{vsys}"))

        # 去重并排序
        unique = {}
        for dest, mask, nh, desc in detail_routes:
            key = (dest, mask, nh)
            if key not in unique:
                unique[key] = (dest, mask, nh, desc)
        detail_routes = list(unique.values())
        detail_routes = sort_routes_by_dest(detail_routes)

        for dest, mask, nh, desc in detail_routes:
            route_cmds.append(ROUTE_TEMPLATE.format(dest=dest, mask=mask, nh=nh, desc=desc))

    # 防火墙：为每个非 public VRF 添加默认路由指向 FW 的 VIP
    vrf_default = defaultdict(set)
    for c in peer_connections:
        vrf = c["remote_vrf"]
        if vrf and vrf.lower() not in PUBLIC_VRF_KEYWORDS and c["fw_ip3"]:
            desc = f"FW_{vrf}"
            vrf_default[vrf].add((c["fw_ip3"], desc))
    for vrf, hop_set in vrf_default.items():
        # 按 IP 排序
        hop_list = sorted([(ipaddress.IPv4Address(nh), nh, desc) for nh, desc in hop_set])
        for _, nh, desc in hop_list:
            route_cmds.append(ROUTE_VPN_TEMPLATE.format(vrf=vrf, nh=nh, desc=desc))
    # 负载侧路由（业务路由，VPN实例）
    if lb_connections:
        for lb in lb_connections:
            vrf = lb.get("remote_vrf")
            next_hop = lb.get("next_hop")
            if not vrf or not next_hop:
                continue
            for route in lb.get("routes", []):
                if not route:
                    continue
                dest, mask = parse_route(route)
                desc = f"LB_{vrf}"
                route_cmds.append(f"ip route-static vpn-instance {vrf} {dest} {mask} {next_hop} description {desc}")

    # 去重并排序（默认路由优先）
    route_cmds = list(dict.fromkeys(route_cmds))
    def route_sort_key(cmd):
        # 提取 vpn-instance 名称（若有）
        vpn_match = re.search(r'ip route-static\s+vpn-instance\s+(\S+)', cmd)
        vpn_name = vpn_match.group(1) if vpn_match else None
        # 提取目的 IP
        ip_match = re.search(r'ip route-static(?:\s+vpn-instance\s+\S+)?\s+(\d+\.\d+\.\d+\.\d+)', cmd)
        dest_ip = ip_match.group(1) if ip_match else "255.255.255.255"
        is_default = (dest_ip == "0.0.0.0")
        # 排序键：无VPN的排在前面，有VPN的按vpn名称，再默认路由优先，最后按目的IP
        return (0 if vpn_name is None else 1,
                vpn_name if vpn_name else "",
                0 if is_default else 1,
                ipaddress.IPv4Address(dest_ip))

    route_cmds.sort(key=route_sort_key)

    if route_cmds:
        lines.extend(route_cmds)
        lines.append("#")
    lines.append(COMMIT_TEMPLATE)
    lines.append("#\n\n")
    return "\n".join(lines)

# ======================== 回退脚本生成函数 ========================

def generate_rollback_ce(device_name, all_connections, lb_connections=None):
    """
    生成交换机（CE）设备的回退脚本。
    支持防火墙连接和负载连接。
    """
    lines = []
    lines.append(f"{device_name}\n\n#\n{SYSTEM_TEMPLATE}\n#\n")

    # 筛选与该设备相关的防火墙连接
    conns = [c for c in all_connections if device_name in split_device_names(c.get('remote_name', ''))]
    # 筛选与该设备相关的负载连接
    lb_conns = []
    if lb_connections:
        lb_conns = [lb for lb in lb_connections if device_name in split_device_names(lb.get('remote_name', ''))]
    if not conns and not lb_conns:
        return ""

    # 1. 收集数据
    # VRF实例（仅防火墙连接可能创建）
    vrfs = set()
    for c in conns:
        vrf = c.get('remote_vrf', '')
        if vrf and vrf.lower() not in PUBLIC_VRF_KEYWORDS:
            vrfs.add(vrf)

    # 路由收集（包括防火墙和负载）
    route_cmds = []  # 存储所有正向路由命令（不带description）

    # 防火墙路由（原有逻辑）
    has_public = any(c.get('remote_vrf', '').lower() in PUBLIC_VRF_KEYWORDS for c in conns)
    if has_public:
        vsys_public_vip = {}
        vsys_routes = defaultdict(set)
        for c in all_connections:
            vsys = c.get('vsys', '')
            if not vsys:
                continue
            vrf = (c.get('remote_vrf', '') or 'public').lower()
            if vrf in PUBLIC_VRF_KEYWORDS and c.get('fw_ip3'):
                vsys_public_vip[vsys] = c['fw_ip3']
            for route in c.get('routes', []):
                if route and route != "0.0.0.0/0":
                    vsys_routes[vsys].add(route)
        detail_routes = []
        for vsys, route_set in vsys_routes.items():
            vip = vsys_public_vip.get(vsys)
            if not vip:
                continue
            for route in route_set:
                dest, mask = parse_route(route)
                detail_routes.append((dest, mask, vip))
        unique = {}
        for dest, mask, nh in detail_routes:
            key = (dest, mask, nh)
            if key not in unique:
                unique[key] = key
        detail_routes = list(unique.values())
        detail_routes = sort_routes_by_dest([(d, m, n, '') for d, m, n in detail_routes])
        for dest, mask, nh, _ in detail_routes:
            route_cmds.append(f"ip route-static {dest} {mask} {nh}")

    # 非public VRF的默认路由（防火墙）
    vrf_default = {}
    for c in conns:
        vrf = c.get('remote_vrf', '')
        if vrf and vrf.lower() not in PUBLIC_VRF_KEYWORDS and c.get('fw_ip3'):
            vrf_default.setdefault(vrf, set()).add(c['fw_ip3'])
    for vrf, hop_set in vrf_default.items():
        for nh in hop_set:
            route_cmds.append(f"ip route-static vpn-instance {vrf} 0.0.0.0 0.0.0.0 {nh}")

    # 负载路由（VPN实例）
    for lb in lb_conns:
        vrf = lb.get('remote_vrf')
        next_hop = lb.get('next_hop')
        if not vrf or not next_hop:
            continue
        for route in lb.get('routes', []):
            if not route:
                continue
            dest, mask = parse_route(route)
            route_cmds.append(f"ip route-static vpn-instance {vrf} {dest} {mask} {next_hop}")

    # 去重路由命令
    route_cmds = list(dict.fromkeys(route_cmds))

    # VLAN、Vlanif、Trunk透传vlan（合并防火墙和负载）
    vlans = set()
    vlanif_vlans = set()
    trunk_vlans = defaultdict(set)

    for c in conns:
        vlan = c.get('ce_vlan')
        if vlan is not None:
            vlans.add(vlan)
            vlanif_vlans.add(vlan)
            agg_str = c.get('remote_aggregate', '')
            if agg_str:
                intfs = re.split(r'<br>|\n|\r\n', agg_str)
                intfs = [i.strip() for i in intfs if i.strip()]
                for intf in intfs:
                    trunk_vlans[intf].add(vlan)
    for lb in lb_conns:
        vlan = lb.get('ce_vlan')
        if vlan is not None:
            vlans.add(vlan)
            vlanif_vlans.add(vlan)
            agg_list = lb.get('ce_aggregate_list', [])
            for intf in agg_list:
                trunk_vlans[intf].add(vlan)

    # 前缀列表（仅防火墙）
    vsys_detail = defaultdict(set)
    for c in all_connections:
        if device_name not in split_device_names(c.get('remote_name', '')):
            continue
        vsys = c.get('vsys')
        if not vsys:
            continue
        for route in c.get('routes', []):
            if route and route != "0.0.0.0/0":
                if '/' in route:
                    dest, prefix = route.split('/')
                    prefixlen = int(prefix)
                else:
                    dest = route
                    prefixlen = 32
                vsys_detail[vsys].add((dest, prefixlen))
    name_routes = defaultdict(set)
    for c in all_connections:
        if device_name not in split_device_names(c.get('remote_name', '')):
            continue
        pl_name = c.get('prefix_list_name')
        if not pl_name:
            continue
        vsys = c.get('vsys')
        if not vsys:
            continue
        routes = vsys_detail.get(vsys, set())
        if routes:
            name_routes[pl_name].update(routes)

    # 2. 生成回退命令
    def add_module(cmds):
        if cmds:
            lines.extend(cmds)
            lines.append("#\n")

    # a. undo vpn-instance
    cmds = []
    for vrf in sorted(vrfs):
        cmds.append(f"undo ip vpn-instance {vrf}\n")
    add_module(cmds)

    # b. undo route-policy (仅新建)
    new_prefix_names = set()
    for c in all_connections:
        if device_name not in split_device_names(c.get('remote_name', '')):
            continue
        pl_name = c.get('prefix_list_name')
        if pl_name and '新建' in pl_name:
            new_prefix_names.add(pl_name.replace('新建', ''))
    cmds = []
    for name in sorted(new_prefix_names):
        cmds.append(f"undo route-policy {name}\n")
    add_module(cmds)

    # c. undo ip-prefix (所有) - 逐条删除
    cmds = []
    for name in sorted(name_routes.keys()):
        for dest, prefixlen in sorted(name_routes[name], key=lambda x: (ipaddress.IPv4Address(x[0]), x[1])):
            cmds.append(f"undo ip ip-prefix {name} permit {dest} {prefixlen}\n")
    add_module(cmds)

    # d. undo static routes (包括普通和VPN实例)
    cmds = []
    for route_cmd in route_cmds:
        undo_cmd = route_cmd.replace("ip route-static", "undo ip route-static")
        cmds.append(undo_cmd + "\n")
    add_module(cmds)

    # e. interface 聚合组 \n undo port trunk allow-pass vlan
    cmds = []
    for intf in sorted(trunk_vlans.keys(), key=interface_sort_key):
        vlan_set = trunk_vlans[intf]
        if not vlan_set:
            continue
        vlan_str = format_vlan_list(vlan_set)
        cmds.append(f"interface {intf}\n")
        cmds.append(f" undo port trunk allow-pass vlan {vlan_str}\n")
    add_module(cmds)

    # f. undo vlanif
    cmds = []
    for vlan in sorted(vlanif_vlans):
        cmds.append(f"undo interface Vlanif{vlan}\n")
    add_module(cmds)

    # g. undo vlan batch
    cmds = []
    if vlans:
        vlan_cmds = split_vlan_batch(vlans, MAX_GROUPS_PER_LINE)
        for cmd in vlan_cmds:
            undo_cmd = cmd.replace("vlan batch", "undo vlan batch")
            cmds.append(undo_cmd + "\n")
    add_module(cmds)

    lines.append(f"{COMMIT_TEMPLATE}\n#\n\n")
    return ''.join(lines)

def generate_rollback_fw(device_name, all_connections, role='active'):
    """
    生成防火墙（主或备）的回退脚本。
    role: 'active' 或 'standby'
    备墙只对扩容场景的接口进行 undo vrrp 。
    """
    lines = []
    lines.append(f"{device_name}\n\n#\n{SYSTEM_TEMPLATE}\n#\n")

    if role == 'active':
        conns = [c for c in all_connections if c.get('fw_device1') == device_name]
    else:
        conns = [c for c in all_connections if c.get('fw_device2') == device_name]

    if not conns:
        return ""

    def add_module(cmds):
        if cmds:
            lines.extend(cmds)
            lines.append("#\n")

    # ---- 构建每个 VSYS 的场景（基于主墙连接） ----
    # 获取主墙设备名（取第一个连接中的 fw_device1）
    main_device = None
    for c in all_connections:
        if c.get('fw_device1'):
            main_device = c['fw_device1']
            break
    if not main_device:
        main_device = device_name  # 如果找不到，回退

    vsys_scenario = {}
    for c in all_connections:
        vsys = c.get('vsys', '')
        if not vsys:
            continue
        if vsys in vsys_scenario:
            continue
        # 只分析主墙的连接，避免重复
        main_conns = [cc for cc in all_connections if cc.get('fw_device1') == main_device and cc.get('vsys') == vsys]
        if not main_conns:
            continue
        # 判断场景
        has_empty_public = any(
            cc.get('remote_vrf', '').lower() in PUBLIC_VRF_KEYWORDS and not cc.get('fw_int')
            for cc in main_conns
        )
        has_nonempty_public = any(
            cc.get('remote_vrf', '').lower() in PUBLIC_VRF_KEYWORDS and cc.get('fw_int')
            for cc in main_conns
        )
        vsys_scenario[vsys] = 'new' if has_nonempty_public else 'expand'

    # ---- 备墙处理 ----
    if role == 'standby':
        # 收集扩容场景的接口
        intf_vrid = {}
        for c in conns:
            intf = c.get('fw_int')
            if not intf:
                continue
            vsys = c.get('vsys', '')
            if vsys_scenario.get(vsys) == 'expand':
                intf_vrid[intf] = c.get('vrid', DEFAULT_VRID)
        # 1. 删除 VRRP（仅扩容接口）
        cmds = []
        for intf in sorted(intf_vrid.keys(), key=interface_sort_key):
            vrid = intf_vrid[intf]
            cmds.append(f"interface {intf}\n")
            cmds.append(f" undo vrrp vrid {vrid}\n")
            cmds.append(" y\n")
        add_module(cmds)
        lines.append(f"return\n\n")
        return ''.join(lines)

    # ---- 主墙处理（保持原有逻辑，但使用 vsys_scenario 辅助） ----
    # 以下为主墙原有代码，保持不变（但为了统一，也可微调）
    vsys_conns = defaultdict(list)
    for c in conns:
        vsys = c.get('vsys', '')
        if vsys:
            vsys_conns[vsys].append(c)

    for vsys in sorted(vsys_conns.keys()):
        vsys_conns_list = vsys_conns[vsys]
        scenario = vsys_scenario.get(vsys, 'expand')

        intfs = set()
        vrid_map = {}
        for c in vsys_conns_list:
            intf = c.get('fw_int')
            if intf:
                intfs.add(intf)
                vrid_map[intf] = c.get('vrid', DEFAULT_VRID)

        routes = []
        for c in vsys_conns_list:
            next_hop = c.get('remote_ip')
            if not next_hop:
                continue
            for route in c.get('routes', []):
                if not route:
                    continue
                dest, mask = parse_route(route)
                routes.append((dest, mask, next_hop))
        unique = {}
        for dest, mask, nh in routes:
            key = (dest, mask, nh)
            if key not in unique:
                unique[key] = key
        routes = list(unique.values())
        routes.sort(key=lambda x: (0 if x[0] == '0.0.0.0' else 1, ipaddress.IPv4Address(x[0])))

        zones = set()
        for c in vsys_conns_list:
            zone = c.get('zone', '')
            if zone and zone.lower() not in BUILTIN_ZONES:
                zones.add(zone)

        if scenario == 'new':
            # 新建：删除 vsys 和接口
            cmds = []
            cmds.append(f"undo vsys name {vsys}\n")
            cmds.append(" y\n")
            add_module(cmds)

            cmds = []
            for intf in sorted(intfs, key=interface_sort_key):
                cmds.append(f"undo interface {intf}\n")
            add_module(cmds)

        else:  # 扩容
            # 1. 删除 VRRP
            cmds = []
            for intf in sorted(intfs, key=interface_sort_key):
                vrid = vrid_map.get(intf)
                if vrid is not None:
                    cmds.append(f"interface {intf}\n")
                    cmds.append(f" undo vrrp vrid {vrid}\n")
                    cmds.append(" y\n")
            add_module(cmds)

            # 2. 取消接口分配
            if intfs:
                cmds = []
                cmds.append(f"vsys name {vsys}\n")
                for intf in sorted(intfs, key=interface_sort_key):
                    cmds.append(f" undo assign interface {intf}\n")
                    cmds.append(" y\n")
                add_module(cmds)

            # 3. 删除路由和 zone（合并）
            combined = []
            if routes or zones:
                combined.append(f"switch vsys {vsys}\n")
                combined.append("system\n")
                if routes:
                    for dest, mask, nh in routes:
                        combined.append(f"undo ip route-static {dest} {mask} {nh}\n")
                combined.append("#\n")
                # 只有接口存在时，zone才可能被创建，才需要删除
                if zones and intfs:
                    for zone in sorted(zones):
                        combined.append(f"undo firewall zone name {zone}\n")
                        combined.append(" y\n")
                combined.append("return\nsystem\n")
                add_module(combined)

            # 4. 删除接口
            cmds = []
            for intf in sorted(intfs, key=interface_sort_key):
                cmds.append(f"undo interface {intf}\n")
            add_module(cmds)
    lines.append(f"return\n\n")
    return ''.join(lines)


def interface_sort_key(intf_name):
    """用于接口排序，确保自然顺序"""
    # 简单实现，可复用原脚本中的interface_sort_key
    base = intf_name
    sub = 0
    if '.' in intf_name:
        base, sub_part = intf_name.split('.', 1)
        try:
            sub = int(sub_part)
        except ValueError:
            sub = 0
    if base.lower().startswith('vlanif'):
        try:
            vlan_num = int(base.lower().replace('vlanif', ''))
            return (0, vlan_num, sub)
        except:
            return (0, 0, sub)
    if base.lower().startswith('eth-trunk'):
        try:
            trunk_num = int(base.lower().replace('eth-trunk', ''))
            return (1, trunk_num, sub)
        except:
            return (1, 0, sub)
    match = re.search(r'(\d+)/(\d+)/(\d+)', base)
    if match:
        slot = int(match.group(1))
        subslot = int(match.group(2))
        port = int(match.group(3))
        return (2, slot, subslot, port, sub)
    return (3, 0, 0, 0, 0, intf_name)

def main(file_path, sheet_name, output_dir, rollback_dir, global_device_info):
    """
    主函数：
    1. 解析 Excel
    2. 生成主用防火墙脚本
    3. 生成备用防火墙脚本
    4. 按 CE 设备分组生成脚本
    """

    # 加载配置文件
    def load_config():
        """
        加载设备名称映射配置文件（JSON格式）。
        如果文件不存在，则生成默认配置并退出。
        返回：DEVICE_MAP（设备名→{as, router_id}），
            VRF_SUBINT_MAP（VRF名→subint值），
            PUBLIC_VRF_KEYWORDS（公共VRF关键字集合，小写）
        """
        if not os.path.exists(global_device_info):
            # 默认配置示例
            default_config = {
                "DEVICE_MAP": {
                    "TEST-DXCORE-W01": {"as": 200, "router_id": "1.1.1.1"},
                    "TEST-DXCORE-W02": {"as": 200, "router_id": "1.1.1.2"},
                },
                "VRF_SUBINT_MAP": {
                    "TEST_EX": 402,
                    "TEST_EX_MGMT": 406,
                },
                "PUBLIC_VRF_KEYWORDS": ["public"]
            }
            with open(global_device_info, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            print(f"已生成配置文件 {global_device_info}，请填写后重新运行脚本。")
            exit(0)
        with open(global_device_info, 'r', encoding='utf-8') as f:
            config = json.load(f)
        # 读取公共VRF关键字列表，若无则默认为 ["public"]
        public_keywords = config.get("PUBLIC_VRF_KEYWORDS", ["public"])
        public_set = {kw.lower() for kw in public_keywords}
        return config['DEVICE_MAP'], config['VRF_SUBINT_MAP'], public_set

    # 加载全局配置
    global DEVICE_MAP, VRF_SUBINT_MAP, PUBLIC_VRF_KEYWORDS
    DEVICE_MAP, VRF_SUBINT_MAP, PUBLIC_VRF_KEYWORDS = load_config()



    print("="*60)
    print(f"开始处理Sheet: {sheet_name}")
    firewall_conns, lb_conns = parse_excel(file_path, sheet_name)

    os.makedirs(output_dir, exist_ok=True)
    success_count = 0
    rollback_count = 0
    
    # 获取主备防火墙设备名（取第一个连接中的设备名）
    active_devices = {c["fw_device1"] for c in firewall_conns if c["fw_device1"]}
    standby_devices = {c["fw_device2"] for c in firewall_conns if c["fw_device2"]}
    main_device = list(active_devices)[0] if active_devices else "TEST-FW-W01"
    standby_device = list(standby_devices)[0] if standby_devices else "TEST-FW-W02"

    # 生成主用防火墙配置（追加写入文件）
    fw_active = generate_fw_active(firewall_conns, main_device, sheet_name)
    fw_active = remove_empty_lines(fw_active)
    with open(os.path.join(output_dir, f"{main_device}.txt"), "a", encoding="utf-8") as f:
        f.write(fw_active)
    print(f"已生成变更脚本: {os.path.join(output_dir, f'{main_device}.txt')}")
    success_count += 1
    # 生成备用防火墙配置
    fw_standby = generate_fw_standby(firewall_conns, standby_device)
    fw_standby = remove_empty_lines(fw_standby)
    with open(os.path.join(output_dir, f"{standby_device}.txt"), "a", encoding="utf-8") as f:
        f.write(fw_standby)
    print(f"已生成变更脚本: {os.path.join(output_dir, f'{standby_device}.txt')}")
    success_count += 1
    
    # 按CE设备分组（防火墙）
    peer_groups = defaultdict(list)
    for c in firewall_conns:
        if c["remote_name"]:
            peer_groups[c["remote_name"]].append(c)

    # 按CE设备分组（负载）
    lb_peer_groups = defaultdict(list)
    for lb in lb_conns:
        if lb.get("remote_name"):
            lb_peer_groups[lb["remote_name"]].append(lb)

    # 合并所有设备名（防火墙和负载的设备名）
    all_device_names = set(peer_groups.keys()) | set(lb_peer_groups.keys())
    for cluster_name in all_device_names:
        device_list = split_device_names(cluster_name)
        for dev in device_list:
            if not dev:
                continue
            # 获取该设备的防火墙连接和负载连接
            fw_conns = peer_groups.get(cluster_name, [])
            lb_conns_for_dev = lb_peer_groups.get(cluster_name, [])
            conf = generate_peer_device(fw_conns, firewall_conns, dev, lb_connections=lb_conns_for_dev)
            conf = remove_empty_lines(conf)
            filename = os.path.join(output_dir, f"{dev}.txt")
            with open(filename, "a", encoding="utf-8") as f:
                f.write(conf)
            print(f"已生成变更脚本: {filename}")
            success_count += 1
    
    # ========== 生成回退脚本 ==========

    os.makedirs(rollback_dir, exist_ok=True)

    # 1. 交换机回退脚本（每个CE设备）
    # 合并所有设备名（防火墙和负载）
    fw_peer_groups = defaultdict(list)
    for c in firewall_conns:
        if c["remote_name"]:
            fw_peer_groups[c["remote_name"]].append(c)
    lb_peer_groups = defaultdict(list)
    for lb in lb_conns:
        if lb.get("remote_name"):
            lb_peer_groups[lb["remote_name"]].append(lb)

    all_device_names = set(fw_peer_groups.keys()) | set(lb_peer_groups.keys())
    for cluster_name in all_device_names:
        device_list = split_device_names(cluster_name)
        for dev in device_list:
            if not dev:
                continue
            fw_conns = fw_peer_groups.get(cluster_name, [])
            lb_conns_for_dev = lb_peer_groups.get(cluster_name, [])
            rollback_content = generate_rollback_ce(dev, firewall_conns, lb_connections=lb_conns_for_dev)
            if rollback_content:
                rollback_content = remove_empty_lines(rollback_content)
                rollback_file = os.path.join(rollback_dir, f"回退脚本_{dev}.txt")
                with open(rollback_file, 'w', encoding='utf-8') as f:
                    f.write(rollback_content)
                print(f"已生成回退脚本: {rollback_file}")
                rollback_count += 1
    
    # 2. 防火墙主备回退脚本（使用 firewall_conns）
    for role, device_name in [('active', main_device), ('standby', standby_device)]:
        if not device_name:
            continue
        rollback_content = generate_rollback_fw(device_name, firewall_conns, role)
        if rollback_content:
            rollback_content = remove_empty_lines(rollback_content)
            rollback_file = os.path.join(rollback_dir, f"回退脚本_{device_name}.txt")
            with open(rollback_file, 'w', encoding='utf-8') as f:
                f.write(rollback_content)
            print(f"已生成回退脚本: {rollback_file}")
            rollback_count += 1
    
    print(f"\n共生成 {success_count} 个变更脚本，共 {rollback_count} 个回退脚本")
    print("="*60)

if __name__ == "__main__":
    main(FILE_PATH, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, GLOBAL_DEVICE_INFO)