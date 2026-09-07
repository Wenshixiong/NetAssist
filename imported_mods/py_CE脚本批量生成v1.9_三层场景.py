#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import openpyxl
import os
import re
import json
from collections import defaultdict

# ================== 用户配置区（所有可自定义变量） ==================
GLOBAL_DEVICE_INFO = "设备名称映射表.json"
EXCEL_FILE = 'excel_CE脚本批量生成v1.9_三层场景.xlsx'
SHEET_NAME = "三层场景"
OUTPUT_FOLDER = "output"
ROLLBACK_DIR = os.path.join(OUTPUT_FOLDER, "回退脚本")
VLANIF_DEFAULT_GATEWAY_MASK = "255.255.255.0"
VLANIF_DEFAULT_MAC_ADDRESS = "0000-005e-010d"

OSPF_AREA = "0.0.0.0"
OSPF_NETWORK_MASK = "0.0.0.0"

BGP_DEFAULT_NETWORK_MASK = "255.255.255.0"
BGP_PREFERENCE = "170 170 170"
BGP_MAX_LOAD_BALANCING = 16
BFD_PARAMS = "min-tx-interval 300 min-rx-interval 300 detect-multiplier 5"

DEFAULT_AS = 666
DEFAULT_VRF_SUBINT = 999
DEFAULT_ROUTERID = "66.66.66.66"

VLAN_BATCH_MAX_GROUPS_PER_LINE = 10


_warned_devices = set()
_warned_vrfs = set()

# ================== 配置模板 ==================
VRF_TEMPLATE = """ip vpn-instance {vrf}
 ipv4-family
  route-distinguisher {rd}
#
"""

ETH_TRUNK_LAYER = """interface {interface}
 undo shutdown
 description to {peer_device} {peer_interface} {option}
 mode lacp-static
 undo portswitch
#"""

PHYSICAL_TRUNK_MEMBER = """interface {interface}
 undo shutdown
 description to {peer_device} {peer_interface} {option}
 eth-trunk {trunk_id}
#"""

PHYSICAL_LAYER3_BASE = """interface {interface}
 undo shutdown
 description to {peer_device} {peer_interface} {option}
 undo portswitch"""

IF_OSPF_TEMPLATE = """
 ospf cost 10
 ospf network-type p2p
"""

PHYSICAL_IP_LINE = """
 ip binding vpn-instance {vrf}
 ip address {local_ip} 255.255.255.252"""



SUBINTERFACE_TEMPLATE = """interface {interface}
 dot1q termination vid {vlan}
 description to {peer_device} {peer_interface} {vrf} {option}
 ip binding vpn-instance {vrf}
 ip address {local_ip} 255.255.255.252
"""

# 统一VLANIF模板，掩码和MAC由调用处传入
VLANIF_TEMPLATE = """interface {interface}
 description {desc}
 ip binding vpn-instance {vrf}
 ip address {local_ip} {mask}
{mac_line}
"""

# ================== 排序工具函数 ==================
def remove_empty_lines(text):
    """去除配置文本中的所有空行（仅包含空白字符的行）"""
    lines = text.splitlines()
    non_empty_lines = [line for line in lines if line.strip() != ""]
    return "\n".join(non_empty_lines)

def get_bgp_policies(device_name):
    """返回 (import_policy, export_policy)，若未定义则返回空字符串"""
    info = DEVICE_MAP.get(device_name, {})
    import_policy = info.get("bgp_import_policy", "")
    export_policy = info.get("bgp_export_policy", "")
    # print(export_policy)
    return import_policy, export_policy

def normalize_ip(ip_str):
    """校验并标准化IP地址，去除CIDR掩码部分，返回纯IP字符串"""
    if not ip_str:
        return ip_str
    ip_str = str(ip_str).strip()
    if '/' in ip_str:
        parts = ip_str.split('/', 1)
        ip = parts[0].strip()
        mask_len = parts[1].strip() if len(parts) > 1 else ''
        print(f"警告：IP地址 '{ip_str}' 包含CIDR掩码，已自动提取IP '{ip}'，掩码部分被忽略。请检查Excel中的IP格式。")
        return ip
    return ip_str

def interface_sort_key(intf_name):
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

def sort_configs(configs):
    def key_func(cfg):
        match = re.search(r'interface\s+(\S+)', cfg)
        if match:
            return interface_sort_key(match.group(1))
        return (4, cfg)
    return sorted(configs, key=key_func)

def normalize_trunk_name(name):
    match = re.search(r'(\d+)', name, re.IGNORECASE)
    if match:
        return f"Eth-Trunk{match.group(1)}"
    else:
        print(f"警告：无法从 '{name}' 中提取聚合组编号，保留原样")
        return name

def extract_interface_name(config_str):
    """从配置字符串中提取interface后的接口名"""
    match = re.search(r'^interface\s+(\S+)', config_str, re.MULTILINE)
    if match:
        return match.group(1)
    return None

def ip_sort_key(ip):
    """将IP地址字符串转换为整数元组，用于按数值顺序排序"""
    try:
        return tuple(map(int, ip.split('.')))
    except:
        return (0, 0, 0, 0)

# ================== 设备与VRF查询（支持默认值） ==================
def get_device_info(device_name):
    info = DEVICE_MAP.get(device_name)
    if info is None:
        if device_name not in _warned_devices:
            _warned_devices.add(device_name)
            print(f"警告：设备 '{device_name}' 未在 DEVICE_MAP 中定义，使用默认 AS={DEFAULT_AS}, router-id={DEFAULT_ROUTERID}")
        return DEFAULT_AS, DEFAULT_ROUTERID
    # 使用 .get() 提供默认值，避免 KeyError
    as_num = info.get("as", DEFAULT_AS)
    router_id = info.get("router_id", DEFAULT_ROUTERID)
    return as_num, router_id


def get_device_import(device_name):
    info = DEVICE_MAP.get(device_name, {})
    return info.get("import", {})

def get_rd(device, vrf):
    if not vrf:
        return ""
    as_num, _ = get_device_info(device)
    subint = VRF_SUBINT_MAP.get(vrf)
    if subint is None:
        if vrf not in _warned_vrfs:
            _warned_vrfs.add(vrf)
            print(f"警告：VRF '{vrf}' 未在 VRF_SUBINT_MAP 中定义，使用默认子接口号 {DEFAULT_VRF_SUBINT}")
        subint = DEFAULT_VRF_SUBINT
    return f"{as_num}:{subint}"

def extract_vlan_from_interface(intf_name):
    match = re.search(r'\.(\d+)$', intf_name, re.IGNORECASE) or \
            re.search(r'vlanif(\d+)', intf_name, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def format_vlan_batch(vlan_ids, MAX_GROUPS_PER_LINE):
    if not vlan_ids:
        return ""
    sorted_ids = sorted(set(vlan_ids))
    ranges = []
    start = sorted_ids[0]
    end = sorted_ids[0]
    for num in sorted_ids[1:]:
        if num == end + 1:
            end = num
        else:
            ranges.append((start, end))
            start = end = num
    ranges.append((start, end))
    groups = []
    for s, e in ranges:
        if s == e:
            groups.append(str(s))
        else:
            groups.append(f"{s} to {e}")
    lines = []
    for i in range(0, len(groups), MAX_GROUPS_PER_LINE):
        line_groups = groups[i:i + MAX_GROUPS_PER_LINE]
        lines.append("vlan batch " + " ".join(line_groups))
    return "\n".join(lines)

def detect_interface_type(interface):
    lower = interface.lower()
    if 'vlanif' in lower:
        return 'vlanif'
    if '.' in interface:
        if lower.startswith('eth-trunk'):
            return 'eth-trunk-sub'
        else:
            return 'subinterface'
    if lower.startswith('eth-trunk'):
        return 'eth-trunk'
    return 'physical'

def generate_interface_config(row, is_local):
    if is_local:
        device = row.get('本端设备')
        interface = row.get('本端接口')
        ip = row.get('本端IP')
        peer_device = row.get('对端设备')
        peer_interface = row.get('对端接口')
        peer_ip = row.get('对端IP')
    else:
        device = row.get('对端设备')
        interface = row.get('对端接口')
        ip = row.get('对端IP')
        peer_device = row.get('本端设备')
        peer_interface = row.get('本端接口')
        peer_ip = row.get('本端IP')

    # 校验设备和接口是否为空
    if not device or not interface:
        return None, None, None, None, None, False, None, None, None, None
    # 校验并标准化IP地址
    if ip:
        ip = normalize_ip(ip)
    if peer_ip:
        peer_ip = normalize_ip(peer_ip)

    vrf = row.get('VRF', '').strip() if row.get('VRF') else ''
    # 接口类型（原“是否逃生”列）
    if_type = row.get('接口类型', '').strip().lower() if row.get('接口类型') else ''
    trunk_id_raw = row.get('聚合组ID', '')
    trunk_id = str(trunk_id_raw).strip() if trunk_id_raw is not None else ''
    routing_proto = row.get('路由协议', '').strip().lower() if row.get('路由协议') else ''

    intf_type = detect_interface_type(interface)
    vlan_id = None
    is_vlanif = False

    if intf_type in ('subinterface', 'vlanif', 'eth-trunk-sub'):
        if not ip:
            print(f"警告：{device} 的接口 {interface} 类型为 {intf_type}，但IP为空，跳过")
            return None, None, None, None, None, False, None, None, None, None
        vlan_id = extract_vlan_from_interface(interface)
        if not vlan_id:
            print(f"警告：{device} 的接口 {interface} 无法提取VLAN ID，跳过")
            return None, None, None, None, None, False, None, None, None, None
        if intf_type == 'vlanif':
            is_vlanif = True

    rd = get_rd(device, vrf) if vrf else ""

    # 构建公共参数字典
    params = {
        'interface': interface,
        'local_ip': ip if ip else '',
        'peer_device': peer_device or '',
        'peer_interface': peer_interface or '',
        'vrf': vrf,
        'option': if_type,          # 描述中显示接口类型
        'vlan': vlan_id if vlan_id else '',
    }

    # ----- 物理口 -----
    if intf_type == 'physical':
        if trunk_id:
            trunk_name = normalize_trunk_name(f"Eth-Trunk{trunk_id}")
            params['trunk_id'] = trunk_id
            config = PHYSICAL_TRUNK_MEMBER.format(**params)
            return device, config, None, None, None, False, ('member', trunk_name, peer_device, peer_interface, if_type), (device, ip, peer_device, peer_ip, vrf, if_type), routing_proto, intf_type
        else:
            config = PHYSICAL_LAYER3_BASE.format(**params)
            if ip and vrf:
                config += PHYSICAL_IP_LINE.format(vrf=vrf, local_ip=ip)
                # 若路由协议包含 ospf（包括 ospf新建），追加 OSPF 相关命令
                if 'ospf' in routing_proto:
                    config += IF_OSPF_TEMPLATE
            elif ip and not vrf:
                print(f"警告：设备 {device} 的接口 {interface} 有IP但无VRF，IP将被忽略")
            config += "\n#"
            return device, config, vrf, rd, vlan_id, is_vlanif, None, (device, ip, peer_device, peer_ip, vrf, if_type), routing_proto, intf_type

    # ----- Eth-Trunk 显式定义（忽略） -----
    elif intf_type == 'eth-trunk':
        print(f"注意：发现显式 eth-trunk 行 {interface}，新需求中聚合组由物理口绑定自动生成，此配置将被忽略")
        return None, None, None, None, None, False, None, None, None, None

    # ----- 子接口/聚合子接口 -----
    elif intf_type in ('subinterface', 'eth-trunk-sub'):
        config = SUBINTERFACE_TEMPLATE.format(**params)
        # 若路由协议包含 ospf（包括 ospf新建），追加 OSPF 相关命令
        if 'ospf' in routing_proto:
            config += IF_OSPF_TEMPLATE
        config += "\n#"
        return device, config, vrf, rd, vlan_id, is_vlanif, None, (device, ip, peer_device, peer_ip, vrf, if_type), routing_proto, intf_type

    # ----- VLANIF -----
    elif intf_type == 'vlanif':
        # 根据接口类型决定描述、掩码和MAC
        if if_type == 'gateway':
            desc = f"gateway {vrf}"
            mask = VLANIF_DEFAULT_GATEWAY_MASK
            mac_line = f" mac-address {VLANIF_DEFAULT_MAC_ADDRESS}"
        else:
            # 普通互联或逃生
            desc = f"to {peer_device} {peer_interface} {vrf} {if_type}"
            mask = "255.255.255.252"
            mac_line = ""   # 逃生和普通互联不加MAC

        # 使用统一模板
        config = VLANIF_TEMPLATE.format(
            interface=interface,
            desc=desc,
            vrf=vrf,
            local_ip=ip,
            mask=mask,
            mac_line=mac_line
        )
        # 若路由协议包含 ospf（包括 ospf新建），追加 OSPF 相关命令
        if 'ospf' in routing_proto:
            config += IF_OSPF_TEMPLATE
        # 去除多余空行（当mac_line为空时）
        if not mac_line:
            config = config.replace("\n\n", "\n")
        config += "\n#"
        return device, config, vrf, rd, vlan_id, is_vlanif, None, (device, ip, peer_device, peer_ip, vrf, if_type), routing_proto, intf_type

    else:
        print(f"警告：未知接口类型 '{intf_type}'，跳过")
        return None, None, None, None, None, False, None, None, None, None

# ================== 新增：VLANIF 范围解析函数 ==================
def parse_vlanif_range(intf_str):
    """
    解析 vlanif 接口范围，如 "vlanif2001-2010" 或 "Vlanif2001-2010"
    返回接口名列表，若格式错误返回 None
    """
    match = re.match(r'(vlanif)(\d+)-(\d+)', intf_str, re.IGNORECASE)
    if not match:
        return None
    prefix = match.group(1)      # 保留原始大小写
    start = int(match.group(2))
    end = int(match.group(3))
    if start > end:
        raise ValueError(f"Invalid range: {intf_str}")
    return [f"{prefix}{i}" for i in range(start, end+1)]

def parse_ip_range(ip_str):
    """
    解析 IP 范围，支持四段中任意一段为范围，如 "100.1.1-10.1" 或 "100-110.1.1.1"
    返回 IP 列表，若格式错误抛出异常
    """
    if not ip_str:
        return []
    ip_str = str(ip_str).strip()
    if '-' not in ip_str:
        return [ip_str]
    parts = ip_str.split('.')
    if len(parts) != 4:
        raise ValueError(f"Invalid IP format: {ip_str}")
    range_index = -1
    for i, p in enumerate(parts):
        if '-' in p:
            if range_index != -1:
                raise ValueError(f"Multiple ranges in IP: {ip_str}")
            range_index = i
    if range_index == -1:
        return [ip_str]   # 理论上不会发生
    try:
        start_str, end_str = parts[range_index].split('-')
        start = int(start_str)
        end = int(end_str)
    except:
        raise ValueError(f"Invalid range in IP: {parts[range_index]}")
    if start > end:
        raise ValueError(f"Invalid range: start {start} > end {end}")
    ip_list = []
    for val in range(start, end+1):
        new_parts = parts.copy()
        new_parts[range_index] = str(val)
        ip_list.append('.'.join(new_parts))
    return ip_list

def expand_row(row_data):
    """
    将一行数据（可能包含 vlanif 范围）展开为多行（每个接口一行）
    返回列表，每项为一个 dict（与 row_data 结构相同，但接口和 IP 被替换）
    若发生错误则返回 None
    """
    local_intf = row_data.get('本端接口')
    local_ip = row_data.get('本端IP')
    peer_intf = row_data.get('对端接口')
    peer_ip = row_data.get('对端IP')

    # 标准化 IP（去除 CIDR 掩码）
    if local_ip:
        local_ip = normalize_ip(local_ip)
    if peer_ip:
        peer_ip = normalize_ip(peer_ip)

    # ----- 解析本端 -----
    local_intfs = []
    local_ips = []
    if local_intf and local_intf.lower().startswith('vlanif') and '-' in local_intf:
        intf_list = parse_vlanif_range(local_intf)
        if intf_list is None:
            print(f"警告：无法解析本端接口范围 '{local_intf}'，跳过该行")
            return None
        local_intfs = intf_list
        # 解析 IP
        if local_ip:
            try:
                ip_list = parse_ip_range(local_ip)
            except Exception as e:
                print(f"错误：解析本端IP '{local_ip}' 失败：{e}，跳过该行")
                return None
            if not ip_list:
                print(f"警告：本端IP为空，跳过该行")
                return None
        else:
            print(f"警告：本端IP为空，跳过该行")
            return None
        # 数量校验
        if len(local_intfs) != len(ip_list):
            if len(ip_list) == 1:
                # 单个IP，自动复制
                ip_list = ip_list * len(local_intfs)
                print(f"警告：本端接口数量 {len(local_intfs)} 与IP数量 1 不一致，已自动复制IP '{ip_list[0]}' 到所有接口")
            else:
                print(f"错误：本端接口数量 {len(local_intfs)} 与IP数量 {len(ip_list)} 不一致，跳过该行")
                return None
        local_ips = ip_list
    else:
        # 非范围：单接口、单IP
        local_intfs = [local_intf] if local_intf else []
        local_ips = [local_ip] if local_ip else []
        if local_intf and not local_ip:
            print(f"提示：本端接口 '{local_intf}' 缺少IP，跳过该行")
    

    # ----- 解析对端 -----
    peer_intfs = []
    peer_ips = []
    if peer_intf and peer_intf.lower().startswith('vlanif') and '-' in peer_intf:
        intf_list = parse_vlanif_range(peer_intf)
        if intf_list is None:
            print(f"警告：无法解析对端接口范围 '{peer_intf}'，跳过该行")
            return None
        peer_intfs = intf_list
        if peer_ip:
            try:
                ip_list = parse_ip_range(peer_ip)
            except Exception as e:
                print(f"错误：解析对端IP '{peer_ip}' 失败：{e}，跳过该行")
                return None
            if not ip_list:
                print(f"警告：对端IP为空，跳过该行")
                return None
        else:
            print(f"警告：对端IP为空，跳过该行")
            return None
        if len(peer_intfs) != len(ip_list):
            if len(ip_list) == 1:
                ip_list = ip_list * len(peer_intfs)
                print(f"警告：对端接口数量 {len(peer_intfs)} 与IP数量 1 不一致，已自动复制IP '{ip_list[0]}' 到所有接口")
            else:
                print(f"错误：对端接口数量 {len(peer_intfs)} 与IP数量 {len(ip_list)} 不一致，跳过该行")
                return None
        peer_ips = ip_list
    else:
        peer_intfs = [peer_intf] if peer_intf else []
        peer_ips = [peer_ip] if peer_ip else []
        if peer_intf and not peer_ip:
            print(f"提示：对端接口 '{peer_intf}' 缺少IP，跳过该行")


    # 确保两端接口都非空
    if not local_intfs or not peer_intfs:
        print(f"警告：本端或对端接口为空，跳过该行")
        return None

    # 如果两端都是范围，数量必须相等
    if len(local_intfs) > 1 and len(peer_intfs) > 1:
        if len(local_intfs) != len(peer_intfs):
            print(f"错误：本端范围数量 {len(local_intfs)} 与对端范围数量 {len(peer_intfs)} 不一致，跳过该行")
            return None
        total = len(local_intfs)
    else:
        total = max(len(local_intfs), len(peer_intfs))

    expanded = []
    for i in range(total):
        new_row = row_data.copy()
        new_row['本端接口'] = local_intfs[i % len(local_intfs)]
        new_row['本端IP'] = local_ips[i % len(local_ips)] if local_ips else ''
        new_row['对端接口'] = peer_intfs[i % len(peer_intfs)]
        new_row['对端IP'] = peer_ips[i % len(peer_ips)] if peer_ips else ''
        expanded.append(new_row)

    return expanded


# ================== 新增：生成回退脚本 ==================
def generate_rollback_script(device, data):
    lines = []
    lines.append(f"{device}\n\n#\nsystem\n")
    # 辅助：添加模块命令，若非空则追加内容并跟一个 #
    def add_module(commands):
        if commands:
            lines.extend(commands)
            lines.append("#\n")

    # 1. undo vpn-instance
    cmds = []
    for vrf in data['vrfs'].keys():
        cmds.append(f"undo ip vpn-instance {vrf}\n")
    add_module(cmds)

    # 2. undo ospf (仅当未绑定VPN且为新建)
    cmds = []
    for vrf_key, info in data['ospf_info'].items():
        if info['new'] and not vrf_key:
            cmds.append(f"undo ospf {info['process']}\n")
            cmds.append("y\n")
    add_module(cmds)

    # 3. undo bgp (新建)
    cmds = []
    if data['bgp_info']['new']:
        cmds.append(f"undo bgp {data['bgp_info']['as']}\n")
        cmds.append("y\n")
    add_module(cmds)

    # 4. undo route-policy (新建)
    cmds = []
    policies = data.get('policies', {})
    for policy_name, info in policies.items():
        if info.get('has_new'):
            cmds.append(f"undo route-policy {policy_name}\n")
    add_module(cmds)

    # 5. undo ip-prefix (新建)
    cmds = []
    for policy_name, info in policies.items():
        if info.get('has_new'):
            cmds.append(f"undo ip ip-prefix {policy_name} permit 66.66.66.66 32\n")
    add_module(cmds)

    # 6. undo 静态路由 (不带 description)
    cmds = []
    for vrf_key, conns in data['interconnects'].items():
        for conn in conns:
            if conn.get('is_static'):
                next_hop = conn['peer_ip']
                if vrf_key:
                    cmds.append(f"undo ip route-static vpn-instance {vrf_key} 0.0.0.0 0.0.0.0 {next_hop}\n")
                else:
                    cmds.append(f"undo ip route-static 0.0.0.0 0.0.0.0 {next_hop}\n")
    add_module(cmds)

    # 7. undo 子接口 (物理子接口 + 聚合子接口)
    cmds = []
    sub_intfs = set()
    for cfg in data['phy_subint_configs']:
        intf = extract_interface_name(cfg)
        if intf:
            sub_intfs.add(intf)
    for cfg in data['agg_subint_configs']:
        intf = extract_interface_name(cfg)
        if intf:
            sub_intfs.add(intf)
    for intf in sorted(sub_intfs, key=interface_sort_key):
        cmds.append(f"undo interface {intf}\n")
    add_module(cmds)

    # 8. undo 聚合组 (仅当该聚合组没有子接口，即非扩容场景)
    cmds = []
    trunk_names = set(data['trunk_info'].keys())
    trunks_with_sub = set()
    for cfg in data['agg_subint_configs']:
        intf = extract_interface_name(cfg)
        if intf and '.' in intf:
            trunk_part = intf.split('.')[0]
            if trunk_part in trunk_names:
                trunks_with_sub.add(trunk_part)
    for trunk_name in sorted(trunk_names, key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0):
        if trunk_name not in trunks_with_sub:
            cmds.append(f"undo interface {trunk_name}\n")
    add_module(cmds)

    # 9. undo vlanif 接口
    cmds = []
    vlanif_intfs = set()
    for cfg in data['vlanif_configs']:
        intf = extract_interface_name(cfg)
        if intf:
            vlanif_intfs.add(intf)
    for intf in sorted(vlanif_intfs, key=interface_sort_key):
        cmds.append(f"undo interface {intf}\n")
    add_module(cmds)

    # 10. 清空并 shutdown 物理口 (仅当属于新建场景)
    cmds = []
    physical_intfs = set()
    # 独立物理口
    for cfg in data['physical_configs']:
        intf = extract_interface_name(cfg)
        if intf:
            physical_intfs.add(intf)
    # 聚合组成员：仅当聚合组没有子接口（即新建聚合组）时才清空物理口
    for trunk_name, member_configs in data['trunk_members'].items():
        if trunk_name in trunks_with_sub:
            continue
        for cfg in member_configs:
            intf = extract_interface_name(cfg)
            if intf:
                physical_intfs.add(intf)
    for intf in sorted(physical_intfs, key=interface_sort_key):
        cmds.append(f"interface {intf}\n")
        cmds.append(" clear configuration this\n")
        cmds.append(" y\n")
        cmds.append(" shutdown\n")
    add_module(cmds)

    # 11. undo vlan batch
    cmds = []
    if data['vlans']:
        vlan_cmd = format_vlan_batch(data['vlans'], VLAN_BATCH_MAX_GROUPS_PER_LINE)
        vlan_cmd = vlan_cmd.replace("vlan batch", "undo vlan batch")
        cmds.append(vlan_cmd + "\n")
    add_module(cmds)


    lines.append("commit\n#\n\n")

    return ''.join(lines)


# ================== 主函数 ==================
def main(excel_file, sheet_name, output_dir, rollback_dir, global_device_info):
    print("="*60)

    # 加载配置文件 
    def load_config():
        if not os.path.exists(global_device_info):
            default_config = {
                "DEVICE_MAP": {
                    "TEST-DXCORE-W01": {"as": 200, "router_id": "1.1.1.1"},
                    "TEST-DXCORE-W02": {"as": 200, "router_id": "1.1.1.2"},
                },
                "VRF_SUBINT_MAP": {
                    "TEST_EX": 402,
                    "TEST_EX_MGMT": 406,
                }
            }
            with open(global_device_info, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            print(f"已生成配置文件 {global_device_info}，请填写后重新运行脚本。")
            exit(0)
        with open(global_device_info, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config['DEVICE_MAP'], config['VRF_SUBINT_MAP']

    global DEVICE_MAP, VRF_SUBINT_MAP 
    DEVICE_MAP, VRF_SUBINT_MAP = load_config()

    os.makedirs(output_dir, exist_ok=True)
    print(f"开始处理Sheet: {sheet_name}")
    wb = openpyxl.load_workbook(excel_file, data_only=True)
    sheet = wb[sheet_name]

    headers = [cell.value for cell in sheet[1]]
    col_idx = {h: i for i, h in enumerate(headers, start=1)}

    required = ['VRF', '本端设备', '本端接口', '本端IP',
                '对端设备', '对端接口', '对端IP', '接口类型']
    for col in required:
        if col not in col_idx:
            raise ValueError(f"Excel缺少必要列：'{col}'")

    has_trunk_col = '聚合组ID' in col_idx
    has_route_proto_col = '路由协议' in col_idx

    device_data = defaultdict(lambda: {
        'vrfs': {},
        'vlans': set(),
        'has_vlanif': False,
        'trunk_info': {},
        'trunk_members': defaultdict(list),
        'vlanif_configs': [],
        'physical_configs': [],
        'phy_subint_configs': [],
        'agg_subint_configs': [],
        'interconnects': defaultdict(list),
        'routing_protos': defaultdict(set),
        # 新增字段用于回退
        'policies': {},
        'ospf_info': {},
        'bgp_info': {'as': None, 'new': False},

    })

    for row_num in range(2, sheet.max_row + 1):
        row_cells = sheet[row_num]
        row_data = {h: row_cells[col_idx[h]-1].value for h in headers if h in col_idx}

        if all(v is None for v in row_data.values()):
            continue

        if any(isinstance(v, str) and '<' in v for v in row_data.values() if v is not None):
            continue

        # ----- 预处理（与之前相同） -----
        if has_trunk_col:
            trunk_val = row_data.get('聚合组ID')
            row_data['聚合组ID'] = str(trunk_val).strip() if trunk_val is not None else ''
        else:
            row_data['聚合组ID'] = ''

        if has_route_proto_col:
            route_proto_val = row_data.get('路由协议')
            if route_proto_val is not None:
                row_data['路由协议'] = str(route_proto_val).strip().lower()
            else:
                row_data['路由协议'] = ''
        else:
            row_data['路由协议'] = ''

        if_type_val = row_data.get('接口类型')
        if if_type_val is not None:
            row_data['接口类型'] = str(if_type_val).strip().lower()
        else:
            row_data['接口类型'] = ''

        # ----- 展开 VLANIF 范围 -----
        expanded_rows = expand_row(row_data)
        if expanded_rows is None:
            continue

        # ----- 对每个展开行执行原处理逻辑 -----
        for exp_row in expanded_rows:
            # ---- 处理本端 ----
            dev, config, vrf, rd, vlan_id, is_vlanif, trunk_info, conn_info, routing_proto, intf_type = generate_interface_config(exp_row, is_local=True)
            if dev:
                if is_vlanif and vlan_id:
                    device_data[dev]['vlans'].add(int(vlan_id))
                    device_data[dev]['has_vlanif'] = True
                if vrf and rd and vrf not in device_data[dev]['vrfs']:
                    device_data[dev]['vrfs'][vrf] = rd

                if conn_info:
                    local_dev, local_ip, peer_dev, peer_ip, vrf, if_type = conn_info
                    if local_ip and peer_ip:
                        vrf_key = vrf or ''
                        device_data[dev]['interconnects'][vrf_key].append({
                            'local_ip': local_ip,
                            'peer_device': peer_dev,
                            'peer_ip': peer_ip,
                            'vrf': vrf,
                            'if_type': if_type,
                            'is_static': 'static' in routing_proto
                        })
                    if routing_proto:
                        vrf_key = vrf or ''
                        protos = [p.strip() for p in routing_proto.split(',') if p.strip()]
                        device_data[dev]['routing_protos'][vrf_key].update(protos)

                if trunk_info:
                    typ = trunk_info[0]
                    if typ == 'member':
                        trunk_name = trunk_info[1]
                        device_data[dev]['trunk_members'][trunk_name].append(config)
                        if trunk_name not in device_data[dev]['trunk_info']:
                            device_data[dev]['trunk_info'][trunk_name] = {
                                'peer_device': trunk_info[2],
                                'peer_interface': trunk_info[3],
                                'option': trunk_info[4]
                            }
                elif config:
                    if intf_type == 'vlanif':
                        device_data[dev]['vlanif_configs'].append(config)
                    elif intf_type == 'eth-trunk-sub':
                        device_data[dev]['agg_subint_configs'].append(config)
                    elif intf_type == 'subinterface':
                        device_data[dev]['phy_subint_configs'].append(config)
                    else:
                        device_data[dev]['physical_configs'].append(config)

            # ---- 处理对端 ----
            dev, config, vrf, rd, vlan_id, is_vlanif, trunk_info, conn_info, routing_proto, intf_type = generate_interface_config(exp_row, is_local=False)
            if dev:
                if is_vlanif and vlan_id:
                    device_data[dev]['vlans'].add(int(vlan_id))
                    device_data[dev]['has_vlanif'] = True
                if vrf and rd and vrf not in device_data[dev]['vrfs']:
                    device_data[dev]['vrfs'][vrf] = rd

                if conn_info:
                    local_dev, local_ip, peer_dev, peer_ip, vrf, if_type = conn_info
                    if local_ip and peer_ip:
                        vrf_key = vrf or ''
                        device_data[dev]['interconnects'][vrf_key].append({
                            'local_ip': local_ip,
                            'peer_device': peer_dev,
                            'peer_ip': peer_ip,
                            'vrf': vrf,
                            'if_type': if_type,
                            'is_static': 'static' in routing_proto
                        })
                    if routing_proto:
                        vrf_key = vrf or ''
                        protos = [p.strip() for p in routing_proto.split(',') if p.strip()]
                        device_data[dev]['routing_protos'][vrf_key].update(protos)

                if trunk_info:
                    typ = trunk_info[0]
                    if typ == 'member':
                        trunk_name = trunk_info[1]
                        device_data[dev]['trunk_members'][trunk_name].append(config)
                        if trunk_name not in device_data[dev]['trunk_info']:
                            device_data[dev]['trunk_info'][trunk_name] = {
                                'peer_device': trunk_info[2],
                                'peer_interface': trunk_info[3],
                                'option': trunk_info[4]
                            }
                elif config:
                    if intf_type == 'vlanif':
                        device_data[dev]['vlanif_configs'].append(config)
                    elif intf_type == 'eth-trunk-sub':
                        device_data[dev]['agg_subint_configs'].append(config)
                    elif intf_type == 'subinterface':
                        device_data[dev]['phy_subint_configs'].append(config)
                    else:
                        device_data[dev]['physical_configs'].append(config)

    # ---- 生成最终脚本（正向 + 回退） ----


    os.makedirs(rollback_dir, exist_ok=True)   # 创建回退脚本目录
    success_count = 0
    rollback_count = 0



    for device, data in device_data.items():
        # 正向脚本
        filename = os.path.join(output_dir, f"{device}.txt")
        lines = []   # 收集所有配置行

        lines.append(f"{device}\n\n#\nsystem\n")
        # 1. vlan batch
        if data['vlans']:
            lines.append('#\n' + format_vlan_batch(data['vlans'], VLAN_BATCH_MAX_GROUPS_PER_LINE) + '\n')
        lines.append('#\n')
        # 2. VRF
        for vrf, rd in data['vrfs'].items():
            lines.append(VRF_TEMPLATE.format(vrf=vrf, rd=rd))

        # 3. VLANIF
        if data['vlanif_configs']:
            for cfg in sort_configs(data['vlanif_configs']):
                lines.append(cfg + '\n')

        # 4. 聚合组
        all_trunk_configs = []
        trunk_names = sorted(data['trunk_info'].keys(), key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)
        for trunk_name in trunk_names:
            info = data['trunk_info'][trunk_name]
            params = {
                'interface': trunk_name,
                'peer_device': info['peer_device'],
                'peer_interface': info['peer_interface'],
                'option': info['option'],
            }
            cfg = ETH_TRUNK_LAYER.format(**params)
            all_trunk_configs.append(cfg)
        all_trunk_configs.extend(data['agg_subint_configs'])
        if all_trunk_configs:
            for cfg in sort_configs(all_trunk_configs):
                lines.append(cfg + '\n')

        # 5. 物理口及子接口
        all_phy_configs = []
        for trunk_name in sorted(data['trunk_members'].keys()):
            all_phy_configs.extend(data['trunk_members'][trunk_name])
        all_phy_configs.extend(data['physical_configs'])
        all_phy_configs.extend(data['phy_subint_configs'])
        if all_phy_configs:
            for cfg in sort_configs(all_phy_configs):
                lines.append(cfg + '\n')

        # 6. OSPF
        type_map = {}
        for vrf_key, conns in data['interconnects'].items():
            for conn in conns:
                if conn['local_ip']:
                    type_map[conn['local_ip']] = conn['if_type']
        
        import_config = get_device_import(device)

        # ----- 解析 import 中的策略信息 -----
        # policies: {策略名: {'methods': set(), 'has_new': bool}}
        policies = {}
        for proto, items in import_config.items():
            for item in items:
                if '_' in item:
                    method, policy = item.split('_', 1)          
                    # 例: "direct_test67新建" → method="direct", policy="test67新建"
                    has_new = '新建' in policy
                    clean_policy = policy.replace('新建', '')
                    if clean_policy not in policies:
                        policies[clean_policy] = {'methods': set(), 'has_new': False}
                    policies[clean_policy]['methods'].add(method)
                    if has_new:
                        policies[clean_policy]['has_new'] = True
        
         
        # 记录策略信息（用于回退）
        data['policies'] = policies



        ospf_import_methods = import_config.get('ospf', [])

        for vrf_key, protos in data['routing_protos'].items():
            if 'ospf' not in protos and 'ospf新建' not in protos:
                continue
            has_ospf_new = 'ospf新建' in protos
            conns = data['interconnects'].get(vrf_key, [])
            local_ips = {conn['local_ip'] for conn in conns if conn['local_ip']}
            if not local_ips:
                print(f"警告：设备 {device} 的VRF '{vrf_key}' 无互联IP，无法生成OSPF")
                continue

            if vrf_key:
                process = VRF_SUBINT_MAP.get(vrf_key)
                if process is None:
                    print(f"警告：VRF '{vrf_key}' 未在 VRF_SUBINT_MAP 中定义，使用默认进程号 {DEFAULT_VRF_SUBINT}")
                    process = DEFAULT_VRF_SUBINT
            else:
                process = 666

            _, router_id = get_device_info(device)

            # 记录 OSPF 信息（用于回退）
            data['ospf_info'][vrf_key] = {'process': process, 'new': has_ospf_new}

            if has_ospf_new:
                line = f"ospf {process} router-id {router_id}"
                if vrf_key:
                    line += f" vpn-instance {vrf_key}"
                lines.append(line + "\n")
            else:
                lines.append(f"ospf {process}\n")

            
            # 构建方法->策略名映射（仅针对带下划线的项）
            method_to_policy = {}
            for item in import_config.get('ospf', []):
                if '_' in item:
                    method, policy = item.split('_', 1)
                    clean_policy = policy.replace('新建', '')
                    method_to_policy[method] = clean_policy

            # 默认路由通告
            if 'default' in import_config.get('ospf', []):
                lines.append(" default-route-advertise\n")

            # 处理 direct 和 static 导入（普通或带策略）
            for method in ['direct', 'static']:
                # 检查是否在 import 列表中存在（无论是否带下划线）
                has_method = any(item.startswith(method) for item in import_config.get('ospf', []))
                if has_method:
                    policy = method_to_policy.get(method)
                    if policy:
                        lines.append(f" import-route {method} route-policy {policy} type 1\n")
                    else:
                        lines.append(f" import-route {method} type 1\n")


            if has_ospf_new:
                lines.append(" vpn-instance-capability simple\n")
                lines.append("y\n")

            lines.append(f" area {OSPF_AREA}\n")
            for ip in sorted(local_ips, key=ip_sort_key):
                if type_map.get(ip) == 'gateway' and 'direct' in ospf_import_methods:
                    continue
                line = f"  network {ip} {OSPF_NETWORK_MASK}"
                if type_map.get(ip) == 'taosheng':
                    line += " description taosheng"
                lines.append(line + "\n")
            lines.append("#\n")

        # 7. BGP
        has_bgp = any('bgp' in proto for protos in data['routing_protos'].values() for proto in protos)
        if has_bgp:
            as_num, _ = get_device_info(device)
            bgp_import_methods = import_config.get('bgp', [])
            bgp_import_policy_raw, bgp_export_policy_raw = get_bgp_policies(device)
            # ---- 清洗策略名（去掉“新建”）----
            bgp_import_policy = bgp_import_policy_raw.replace('新建', '') if bgp_import_policy_raw else ''
            bgp_export_policy = bgp_export_policy_raw.replace('新建', '') if bgp_export_policy_raw else ''
            # 注册新建策略（若原始含“新建”），并添加 methods={'bgp'} 占位
            for policy_str_raw in [bgp_import_policy_raw, bgp_export_policy_raw]:
                if policy_str_raw and '新建' in policy_str_raw:
                    clean_policy = policy_str_raw.replace('新建', '')
                    if clean_policy not in policies:
                        policies[clean_policy] = {'methods': {'bgp'}, 'has_new': True}
                    else:
                        policies[clean_policy]['has_new'] = True
                        # 若已存在，将 'bgp' 加入 methods 集合（不影响原有 methods）
                        policies[clean_policy]['methods'].add('bgp')
            is_bgp_new = any('bgp新建' in protos for protos in data['routing_protos'].values())

            # 记录 BGP 信息（用于回退）
            data['bgp_info'] = {'as': as_num, 'new': is_bgp_new}

            # 生成 BGP 配置
            lines.append(f"bgp {as_num}\n")
            
            if is_bgp_new:
                _, router_id = get_device_info(device)
                lines.append(f" router-id {router_id}\n")
                lines.append(" advertise lowest-priority all-address-family peer-up delay 60\n")
                lines.append(" private-4-byte-as enable\n\n")
            for vrf_key, conns in data['interconnects'].items():
                if not conns:
                    continue
                vrf_name = vrf_key if vrf_key else None
                if vrf_name:
                    lines.append(f" ipv4-family vpn-instance {vrf_name}\n")
                else:
                    lines.append(" ipv4-family unicast\n")
                lines.append(f"  preference {BGP_PREFERENCE}\n")
                if 'direct' not in bgp_import_methods:
                    gateway_ips = sorted({conn['local_ip'] for conn in conns 
                                        if conn.get('if_type') == 'gateway' and conn.get('local_ip')}, key=ip_sort_key)
                    for ip in gateway_ips:
                        lines.append(f"  network {ip} {BGP_DEFAULT_NETWORK_MASK}\n")
                
                # 构建方法->策略名映射（仅针对带下划线的项）
                method_to_policy_bgp = {}
                for item in import_config.get('bgp', []):
                    if '_' in item:
                        method, policy = item.split('_', 1)
                        clean_policy = policy.replace('新建', '')
                        method_to_policy_bgp[method] = clean_policy

                # 处理 direct、static 和 default
                for method in ['direct', 'static']:
                    has_method = any(item.startswith(method) for item in import_config.get('bgp', []))
                    if has_method:
                        policy = method_to_policy_bgp.get(method)
                        if policy:
                            lines.append(f"  import-route {method} route-policy {policy}\n")
                        else:
                            lines.append(f"  import-route {method}\n")

                if 'default' in import_config.get('bgp', []):
                    lines.append("  default-route imported\n")

                lines.append(f"  maximum load-balancing {BGP_MAX_LOAD_BALANCING}\n")
                sorted_conns = sorted(conns, key=lambda c: ip_sort_key(c['peer_ip']))
                for conn in sorted_conns:
                    if conn.get('if_type') == 'gateway':
                        continue
                    peer_ip = conn['peer_ip']
                    peer_device = conn['peer_device']
                    peer_as, _ = get_device_info(peer_device)
                    lines.append(f"  peer {peer_ip} as-number {peer_as}\n")
                    if conn['if_type'] != 'taosheng':
                        lines.append(f"  peer {peer_ip} bfd {BFD_PARAMS}\n")
                        lines.append(f"  peer {peer_ip} bfd enable\n")
                        if bgp_import_policy:
                            lines.append(f"  peer {peer_ip} route-policy {bgp_import_policy} import\n")
                        if bgp_export_policy:
                            lines.append(f"  peer {peer_ip} route-policy {bgp_export_policy} export\n")
                lines.append("\n")
            lines.append("#\n")

        # 生成包含“新建”的 route-policy 和 ip-prefix
        _, router_id = get_device_info(device)
        # 收集所有需要生成策略的名称（has_new 为 True 且 methods 非空）
        policy_names = [name for name, info in policies.items() if info.get('has_new') and info.get('methods')]
        if policy_names:
            # 1) 集中输出所有 route-policy（按名称排序）
            for policy_name in sorted(policy_names):
                lines.append(f"route-policy {policy_name} permit node 10\n")
                lines.append(f" if-match ip-prefix {policy_name}\n#\n")
                lines.append(f"route-policy {policy_name} deny node 20\n#\n")
            # 2) 集中输出所有 ip-prefix（permit 地址为设备的 router-id，掩码 32）
            for policy_name in sorted(policy_names):
                lines.append(f"ip ip-prefix {policy_name} permit 66.66.66.66 32\n")
            lines.append("#\n")


        # 8. 静态路由
        static_routes_by_vrf = defaultdict(list)
        for vrf_key, conns in data['interconnects'].items():
            for conn in conns:
                if conn.get('is_static', False) and conn['peer_ip']:
                    static_routes_by_vrf[vrf_key].append(conn)
        if static_routes_by_vrf:
            for vrf_key, conns in static_routes_by_vrf.items():
                seen = set()
                for conn in conns:
                    next_hop = conn['peer_ip']
                    if next_hop in seen:
                        continue
                    seen.add(next_hop)
                    desc = " description taosheng" if conn['if_type'] == 'taosheng' else ""
                    if vrf_key:
                        lines.append(f"ip route-static vpn-instance {vrf_key} 0.0.0.0 0.0.0.0 {next_hop}{desc}\n")
                    else:
                        lines.append(f"ip route-static 0.0.0.0 0.0.0.0 {next_hop}{desc}\n")
            lines.append("#\n\n")
        lines.append("commit\n#\n\n")

        # 合并所有内容，去除空行，再写入文件
        full_content = ''.join(lines)
        full_content = remove_empty_lines(full_content)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(full_content)

        print(f"已生成变更脚本: {filename}")
        success_count += 1
        
        # ---- 生成回退脚本 ----
        rollback_content = generate_rollback_script(device, data)
        rollback_filename = os.path.join(rollback_dir, f"回退脚本_{device}.txt")
        with open(rollback_filename, 'w', encoding='utf-8') as f:
            f.write(rollback_content)
        print(f"已生成回退脚本: {rollback_filename}")
        rollback_count += 1

    print(f"\n共生成 {success_count} 个变更脚本，共 {rollback_count} 个回退脚本")
    print("="*60)

if __name__ == '__main__':
    main(EXCEL_FILE, SHEET_NAME, OUTPUT_FOLDER, ROLLBACK_DIR, GLOBAL_DEVICE_INFO)
