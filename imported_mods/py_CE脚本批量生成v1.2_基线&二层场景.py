#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import json
import ipaddress
from openpyxl import load_workbook
from collections import defaultdict


# ===================== 用户自定义配置区 ======================

EXCEL_PATH = "excel_CE脚本批量生成v1.2_基线&二层场景.xlsx"
SHEET_NAME = "基线&二层场景"
TEMPLATE_DIR = "CE批量脚本生成_基线模板"
OUTPUT_DIR = "output"
GLOBAL_DEVICE_INFO = "设备名称映射表.json"
ROLLBACK_DIR = os.path.join(OUTPUT_DIR, "回退脚本")

VLANIF_DEFAULT_GATEWAY_MASK = "255.255.255.0"
VLANIF_DEFAULT_MAC_ADDRESS = "0000-005e-010d"   

DEFAULT_AS = 666
DEFAULT_VRF_SUBINT = 999
MAX_GROUPS_PER_LINE = 10

COLUMN_MAPPING = {
    "脚本设备名称": "<local_sysname>",
    "基线txt名称": "<template_name>",
    "带外地址": "<mgmt_ip>",
    "带外网关地址": "<mgmtip_gw>",
    "双机对端设备名称": "<remote_sysname>",
    "MLAG组优先级": "<mlag_pri>",
    "MLAG组源地址": "<dad_sip>",
    "MLAG组目的地址": "<dad_dip>",
    "指定STP根桥MAC": "<stp_root_mac>",
    "上下行接口VLAN": "<int_vlan>",
    "上下行接口描述": "<int_desc>",
    "业务网关": "<vlanif_gw>",
    "业务网关描述": "<vlanif_desc>",
}

# ================== 配置模板 ==================================

VRF_TEMPLATE = """
ip vpn-instance {vrf}
 ipv4-family
  route-distinguisher {rd}
#"""

VLANIF_TEMPLATE = """
interface Vlanif{vlan_id}
{desc}
{vpn_binding}
 ip address {ip_address} {netmask}
 mac-address {mac}
#"""

ETH_TRUNK_ACCESS_TEMPLATE = """
interface {interface}
{desc}
 port link-type access
 port default vlan {vlan}
 mode lacp-static
{edged}{mlag}#"""

ETH_TRUNK_TRUNK_TEMPLATE = """
interface {interface}
{desc}
 port link-type trunk
 undo port trunk allow-pass vlan 1
{pvid}{allow}{remove}
 mode lacp-static
{edged}{mlag}#"""

ETH_TRUNK_HYBRID_TEMPLATE = """
interface {interface}
{desc}
 port link-type hybrid
{pvid}{tag}{untag}
 mode lacp-static
{edged}{mlag}#"""

PHYSICAL_ACCESS_TEMPLATE = """
interface {interface}
{desc}
 portswitch
 undo shutdown
{port_mode} port link-type access
 port default vlan {vlan}
{edged}#"""

PHYSICAL_TRUNK_TEMPLATE = """
interface {interface}
{desc}
 portswitch
 undo shutdown
{port_mode} port link-type trunk
 undo port trunk allow-pass vlan 1
{pvid}{allow}{edged}#"""

PHYSICAL_HYBRID_TEMPLATE = """
interface {interface}
{desc}
 portswitch
 undo shutdown
{port_mode} port link-type hybrid
{pvid}{tag}{untag}{edged}#"""

PHYSICAL_BUNDLE_TEMPLATE = """
interface {interface}
{desc}
 portswitch
 undo shutdown
{port_mode}
 eth-trunk {group}
{edged}
#"""

ETH_TRUNK_INCREMENT_TEMPLATE = """
interface {interface}
{commands}
#"""

STP_ROOT_TEMPLATE = """
stp bridge-address {mac}
stp instance 0 root primary
"""

# =============================================================

def expand_vlan_range(vlan_str):
    if '-' in vlan_str:
        start, end = vlan_str.split('-')
        return list(range(int(start), int(end) + 1))
    else:
        return [int(vlan_str)]
    
def expand_ip_range(ip_str):
    # 分离掩码
    if '/' in ip_str:
        ip_part, mask = ip_str.split('/', 1)
        mask = '/' + mask
    else:
        ip_part = ip_str
        mask = ''   # 后续在生成 Vlanif 时会补默认掩码

    parts = ip_part.split('.')
    if len(parts) != 4:
        raise ValueError(f"Invalid IP: {ip_str}")

    # 查找第一个包含 '-' 的段
    range_info = None
    for idx, seg in enumerate(parts):
        if '-' in seg:
            a, b = seg.split('-')
            range_info = (idx, int(a), int(b))
            break

    if range_info is None:
        # 无范围，原样返回
        return [ip_str]

    idx, start, end = range_info
    results = []
    for val in range(start, end + 1):
        new_parts = parts.copy()
        new_parts[idx] = str(val)
        new_ip = '.'.join(new_parts) + mask
        results.append(new_ip)
    return results

def cidr_to_address_mask(cidr):
    """将 CIDR 格式（如 '100.1.0.1/24'）转换为 (ip_address, netmask)"""
    try:
        iface = ipaddress.ip_interface(cidr)
        return str(iface.ip), str(iface.netmask)
    except ValueError:
        # 若不是 CIDR，原样返回（可能已是 IP + 掩码）
        return cidr, ''

def expand_description_for_interfaces(desc_template, interfaces):
    """
    根据描述模板和接口列表，生成每个接口的描述字符串列表。
    支持多个 [m-n] 或 [数字] 占位符，按顺序与接口列表一一对应。
    如果占位符个数多于接口数量，则取前 N 个；如果少于，则用最后一个值填充。
    """
    if not desc_template:
        return ['' for _ in interfaces]
    # 提取所有占位符 [数字] 或 [数字-数字]
    placeholders = re.findall(r'\[(\d+)(?:-(\d+))?\]', desc_template)
    if not placeholders:
        return [desc_template for _ in interfaces]

    num_lists = []
    for start, end in placeholders:
        if end:  # 范围
            s, e = int(start), int(end)
            if s > e:
                s, e = e, s
            nums = list(range(s, e+1))
            # 调整长度与接口数量一致
            if len(nums) != len(interfaces):
                if len(nums) < len(interfaces):
                    nums.extend([nums[-1]] * (len(interfaces) - len(nums)))
                else:
                    nums = nums[:len(interfaces)]
            num_lists.append(nums)
        else:  # 单值
            num = int(start)
            num_lists.append([num] * len(interfaces))

    # 确保所有列表长度一致
    for i, lst in enumerate(num_lists):
        if len(lst) != len(interfaces):
            if len(lst) < len(interfaces):
                lst.extend([lst[-1]] * (len(interfaces) - len(lst)))
            else:
                num_lists[i] = lst[:len(interfaces)]

    # 将所有占位符替换为 {}
    desc_pattern = re.sub(r'\[\d+(?:-\d+)?\]', '{}', desc_template)
    descs = []
    for idx in range(len(interfaces)):
        args = [num_lists[i][idx] for i in range(len(num_lists))]
        descs.append(desc_pattern.format(*args))
    return descs

def compress_vlan_set_to_groups(vlan_set):
    if not vlan_set:
        return []
    sorted_vlans = sorted(vlan_set)
    groups = []
    start = sorted_vlans[0]
    end = start
    for v in sorted_vlans[1:]:
        if v == end + 1:
            end = v
        else:
            groups.append(f"{start}" if start == end else f"{start} to {end}")
            start = v
            end = v
    groups.append(f"{start}" if start == end else f"{start} to {end}")
    return groups

def format_vlan_batch_lines(vlan_set, max_groups):
    groups = compress_vlan_set_to_groups(vlan_set)
    if not groups:
        return []
    lines = []
    for i in range(0, len(groups), max_groups):
        line = "vlan batch " + " ".join(groups[i:i+max_groups])
        lines.append(line)
        lines.append("#")
    return lines

def load_device_mapping(json_path):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('DEVICE_MAP', {}), data.get('VRF_SUBINT_MAP', {})
    except Exception as e:
        print(f"警告：加载映射文件失败 ({e})，将使用默认值")
        return {}, {}

def get_column_indices(sheet, mapping):
    header_row = sheet[1]
    header_values = []
    for cell in header_row:
        if cell.value is not None:
            header_values.append(str(cell.value).strip())
        else:
            header_values.append('')
    title_to_idx = {title: idx for idx, title in enumerate(header_values, start=1) if title}
    var_to_col = {}
    for title, var_name in mapping.items():
        if title not in title_to_idx:
            raise ValueError(f"Excel第一行中未找到列标题 '{title}'")
        var_to_col[var_name] = title_to_idx[title]
    if '<template_name>' not in var_to_col:
        raise ValueError("必须包含 '基线txt名称' 映射")
    if '<local_sysname>' not in var_to_col:
        raise ValueError("必须包含 '脚本设备名称' 映射")
    return var_to_col

def read_device_data(sheet, var_to_col):
    devices = []
    for row_idx in range(2, sheet.max_row + 1):
        row_data = {}
        first_cell = sheet.cell(row=row_idx, column=1).value
        if first_cell is None or str(first_cell).strip() == '':
            continue
        for var_name, col_idx in var_to_col.items():
            cell_value = sheet.cell(row=row_idx, column=col_idx).value
            row_data[var_name] = str(cell_value).strip() if cell_value is not None else ''
        devices.append(row_data)
    return devices

def insert_stp_root_commands(content, stp_root_mac):
    lines = content.splitlines(keepends=True)
    target_line = "stp mode rstp"
    insert_block = STP_ROOT_TEMPLATE.format(mac=stp_root_mac)
    insert_lines = [line + '\n' for line in insert_block.splitlines() if line.strip()]

    found_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == target_line or stripped.startswith(target_line):
            found_idx = i
            break

    if found_idx != -1:
        lines[found_idx:found_idx] = insert_lines
    else:
        print(f"警告：未找到 '{target_line}' 行，将 STP 根桥命令追加到文件末尾")
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.extend(insert_lines)
    return ''.join(lines)

def replace_template(template_content, replacements):
    for var, value in replacements.items():
        template_content = template_content.replace(var, value)
    return template_content

def remove_empty_lines(content):
    lines = content.splitlines(keepends=False)
    non_empty_lines = [line for line in lines if line.strip() != '']
    return '\n'.join(non_empty_lines)

def insert_block_before_first_match(content, block, pattern):
    lines = content.splitlines(keepends=True)
    idx = -1
    for i, line in enumerate(lines):
        if re.match(pattern, line.strip(), re.IGNORECASE):
            idx = i
            break
    if idx == -1:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(block)
    else:
        lines.insert(idx, block)
    return ''.join(lines)

def insert_block_after_last_match(content, block, pattern):
    lines = content.splitlines(keepends=True)
    idx = -1
    for i, line in enumerate(lines):
        if re.match(pattern, line.strip(), re.IGNORECASE):
            idx = i
    if idx == -1:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(block)
    else:
        lines.insert(idx + 1, block)
    return ''.join(lines)

# ===================== 二层场景核心解析 ======================

def expand_range_with_keyword(expr_str):
    if not expr_str:
        return None
    if ',' in expr_str:
        parts = expr_str.split(',')
        if len(parts) != 2:
            return None
        range_part, keyword = parts[0].strip(), parts[1].strip()
        if '-' not in range_part:
            return None
        start_end = range_part.split('-')
        if len(start_end) != 2:
            return None
        try:
            start = int(start_end[0])
            end = int(start_end[1])
        except ValueError:
            return None
        if start > end:
            return None
        if keyword == 'all':
            return list(range(start, end + 1))
        elif keyword == 'ji':
            return [i for i in range(start, end + 1) if i % 2 == 1]
        elif keyword == 'ou':
            return [i for i in range(start, end + 1) if i % 2 == 0]
        else:
            return None
    else:
        if '-' in expr_str:
            start_end = expr_str.split('-')
            if len(start_end) != 2:
                return None
            try:
                start = int(start_end[0])
                end = int(start_end[1])
            except ValueError:
                return None
            if start > end:
                return None
            return list(range(start, end + 1))
        else:
            try:
                return [int(expr_str)]
            except ValueError:
                return None

def parse_vlan_set(content):
    if not content or content == 'all':
        return set()
    content = content.replace(',', ' ').replace('-', ' ')
    tokens = content.split()
    vlan_set = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == 'to':
            i += 1
            continue
        if tok.isdigit():
            if i + 2 < len(tokens) and tokens[i+1] == 'to' and tokens[i+2].isdigit():
                start = int(tok)
                end = int(tokens[i+2])
                if start <= end:
                    vlan_set.update(range(start, end+1))
                i += 3
            else:
                vlan_set.add(int(tok))
                i += 1
        else:
            i += 1
    return vlan_set

def format_vlan_range_string(vlan_set):
    if not vlan_set:
        return None
    sorted_vlans = sorted(vlan_set)
    ranges = []
    start = sorted_vlans[0]
    end = start
    for v in sorted_vlans[1:]:
        if v == end + 1:
            end = v
        else:
            ranges.append(f"{start}" if start == end else f"{start} to {end}")
            start = v
            end = v
    ranges.append(f"{start}" if start == end else f"{start} to {end}")
    return ' '.join(ranges)


def parse_description_line(desc_line):
    """
    解析描述行，返回 (target_type, target_list, desc_template)
    target_type: 'group' 或 'interface'
    target_list: 聚合组ID列表 或 接口名称列表
    desc_template: 描述模板（可能包含方括号占位符）
    若解析失败返回 None
    """
    if not desc_line:
        return None
    # 查找 _desc[ 的位置
    marker = '_desc['
    pos = desc_line.lower().find(marker)
    if pos == -1:
        return None
    prefix = desc_line[:pos]  # 目标部分
    desc_start = pos + len(marker)
    last_bracket = desc_line.rfind(']')
    if last_bracket == -1 or last_bracket < desc_start:
        return None
    desc_template = desc_line[desc_start:last_bracket].strip()

    # 1. 聚合组: group[11] 或 group50
    m = re.match(r'^group(\[.*?\]|\d+)$', prefix, re.IGNORECASE)
    if m:
        group_expr = m.group(1)
        if group_expr.startswith('[') and group_expr.endswith(']'):
            range_expr = group_expr[1:-1]
            group_ids = expand_range_with_keyword(range_expr)
            if group_ids:
                return ('group', group_ids, desc_template)
        else:
            try:
                group_id = int(group_expr)
                return ('group', [group_id], desc_template)
            except ValueError:
                pass

    # 2. 物理接口
    # 如果 prefix 包含 '/' 且不包含 'group'，则认为是物理接口
    if '/' in prefix and 'group' not in prefix.lower():
        # 判断是否包含 [ ] 范围
        if '[' in prefix and ']' in prefix:
            # 提取基础部分和端口表达式
            base = prefix[:prefix.index('[')]
            # 去掉末尾的 '/'
            if base.endswith('/'):
                base = base[:-1]
            port_expr = prefix[prefix.index('[')+1:prefix.index(']')]
            # 展开端口号
            port_numbers = expand_range_with_keyword(port_expr)
            if port_numbers:
                # 确定补零宽度
                match_first = re.search(r'\d+', port_expr)
                width = len(match_first.group(0)) if match_first else 1
                interfaces = [f"{base}/{str(p).zfill(width)}".lower() for p in port_numbers]
                return ('interface', interfaces, desc_template)
        else:
            # 单个接口
            return ('interface', [prefix.lower()], desc_template)

    return None


def parse_interface_config(cell_value, desc_cell=None):
    """
    解析上下行接口VLAN列，支持外部描述列。
    返回字典：{'vlan_batch': [str], 'eth_trunks': [str], 'physicals': [str]}
    """
    if not cell_value or not isinstance(cell_value, str):
        return None

    cell_value = cell_value.lower().replace('，', ',')
    lines = [line.strip() for line in cell_value.strip().splitlines() if line.strip()]
    if not lines:
        return None

    desc_lines = []
    if desc_cell and isinstance(desc_cell, str):
        desc_lines = [line.strip() for line in desc_cell.strip().splitlines() if line.strip()]


    all_vlan_ids = set()
    eth_trunk_configs = {}
    eth_trunk_increments = {}
    interface_bindings = {}

    # 第一遍：解析 VLAN 配置
    for idx, line in enumerate(lines):
        parts = line.split('_')
        interface_range = None
        aggregate_group = None
        mode = None
        mode_pvid = None
        port_mode = None
        vlan_conf = None
        vlan_add_conf = None
        vlan_remove_conf = None
        tag_conf = None
        tag_add_conf = None
        tag_remove_conf = None
        untag_conf = None
        untag_add_conf = None
        untag_remove_conf = None
        mlag_flag = False
        edged_flag = False
        desc_text = None
        unknown_fields = []

        for p in parts:
            p = p.strip()
            if not p:
                continue
            if re.match(r'^group\[', p) or re.match(r'^group\d+$', p):
                aggregate_group = p
            elif re.match(r'^[\da-z]+/\d+/\[', p) or re.match(r'^[\da-z]+/\d+/\d+$', p):
                interface_range = p
            elif re.match(r'^port\[(10g|ge)\]$', p):
                match_port = re.match(r'port\[(10g|ge)\]$', p)
                if match_port:
                    raw = match_port.group(1)
                    port_mode = '10G' if raw == '10g' else 'GE'
            elif re.match(r'^access$', p):
                mode = 'access'
                mode_pvid = None
            elif re.match(r'^trunk(\[\d+\])?$', p):
                mode = 'trunk'
                match_pvid = re.search(r'\[(\d+)\]', p)
                mode_pvid = match_pvid.group(1) if match_pvid else None
            elif re.match(r'^hybrid(\[\d+\])?$', p):
                mode = 'hybrid'
                match_pvid = re.search(r'\[(\d+)\]', p)
                mode_pvid = match_pvid.group(1) if match_pvid else None
            elif re.match(r'^vlan\[', p):
                vlan_conf = p
            elif re.match(r'^vlan\+\[', p):
                vlan_add_conf = p
            elif re.match(r'^vlan-\[', p):
                vlan_remove_conf = p
            elif re.match(r'^tag\[', p):
                tag_conf = p
            elif re.match(r'^tag\+\[', p):
                tag_add_conf = p
            elif re.match(r'^tag-\[', p):
                tag_remove_conf = p
            elif re.match(r'^untag\[', p):
                untag_conf = p
            elif re.match(r'^untag\+\[', p):
                untag_add_conf = p
            elif re.match(r'^untag-\[', p):
                untag_remove_conf = p

            elif p == 'mlag':
                mlag_flag = True
            elif p == 'edged':
                edged_flag = True
            else:
                unknown_fields.append(p)

        if unknown_fields:
            print(f"[ERROR] 无法识别的字段: {', '.join(unknown_fields)}")
            return None
        if not aggregate_group and not interface_range:
            print(f"[ERROR] 至少需要聚合组或接口范围: {line}")
            return None


        is_incremental = (vlan_add_conf is not None or vlan_remove_conf is not None or
                          tag_add_conf is not None or tag_remove_conf is not None or
                          untag_add_conf is not None or untag_remove_conf is not None)

        # 解析聚合组编号
        group_ids = []
        if aggregate_group:
            if aggregate_group.startswith('group['):
                match_g = re.search(r'group\[(.*?)\]', aggregate_group)
                if not match_g:
                    print(f"[ERROR] 聚合组格式错误: {aggregate_group}")
                    return None
                expr = match_g.group(1)
                group_ids = expand_range_with_keyword(expr)
                if group_ids is None:
                    print(f"[ERROR] 聚合组表达式无效: {aggregate_group}")
                    return None
            else:
                match_single = re.match(r'group(\d+)$', aggregate_group)
                if match_single:
                    group_ids = [int(match_single.group(1))]
                else:
                    print(f"[ERROR] 聚合组格式错误: {aggregate_group}")
                    return None

        # 解析接口范围
        interfaces = []
        if interface_range:
            if '[' in interface_range:
                match_if = re.match(r'([\da-z]+)(\d+)/(\d+)/\[(.*?)\]', interface_range)
                if not match_if:
                    print(f"[ERROR] 接口范围格式错误: {interface_range}")
                    return None
                if_type = match_if.group(1)
                slot = match_if.group(2)
                subslot = match_if.group(3)
                expr = match_if.group(4)
                port_numbers = expand_range_with_keyword(expr)
                if port_numbers is None:
                    print(f"[ERROR] 接口范围表达式无效: {interface_range}")
                    return None
                interfaces = [f"{if_type}{slot}/{subslot}/{port}" for port in port_numbers]
            else:
                match_if = re.match(r'([\da-z]+)(\d+)/(\d+)/(\d+)$', interface_range)
                if not match_if:
                    print(f"[ERROR] 接口格式错误: {interface_range}")
                    return None
                if_type = match_if.group(1)
                slot = match_if.group(2)
                subslot = match_if.group(3)
                port = match_if.group(4)
                interfaces = [f"{if_type}{slot}/{subslot}/{port}"]

        # 处理增量操作（与之前相同）
        if is_incremental:
            if interfaces:
                print(f"[ERROR] 物理接口不支持增量操作: {line}")
                return None
            if not group_ids:
                print(f"[ERROR] 增量操作必须指定聚合组: {line}")
                return None

            has_trunk_inc = (vlan_add_conf is not None or vlan_remove_conf is not None)
            has_hybrid_inc = (tag_add_conf is not None or tag_remove_conf is not None or
                              untag_add_conf is not None or untag_remove_conf is not None)
            if has_trunk_inc and has_hybrid_inc:
                print(f"[ERROR] 不能同时使用 trunk 和 hybrid 增量: {line}")
                return None

            trunk_add_set = set()
            trunk_remove_set = set()
            tag_add_set = set()
            tag_remove_set = set()
            untag_add_set = set()
            untag_remove_set = set()

            if vlan_add_conf:
                match_a = re.match(r'vlan\+\[(.*?)\]', vlan_add_conf)
                if not match_a:
                    print(f"[ERROR] vlan+ 格式错误: {vlan_add_conf}")
                    return None
                add_content = match_a.group(1).strip()
                if add_content == 'all':
                    print(f"[ERROR] vlan+ 不支持 all")
                    return None
                trunk_add_set = parse_vlan_set(add_content)
                all_vlan_ids.update(trunk_add_set)
            if vlan_remove_conf:
                match_r = re.match(r'vlan-\[(.*?)\]', vlan_remove_conf)
                if not match_r:
                    print(f"[ERROR] vlan- 格式错误: {vlan_remove_conf}")
                    return None
                rem_content = match_r.group(1).strip()
                if rem_content == 'all':
                    print(f"[ERROR] vlan- 不支持 all")
                    return None
                trunk_remove_set = parse_vlan_set(rem_content)

            if tag_add_conf:
                match_a = re.match(r'tag\+\[(.*?)\]', tag_add_conf)
                if not match_a:
                    print(f"[ERROR] tag+ 格式错误: {tag_add_conf}")
                    return None
                add_content = match_a.group(1).strip()
                if add_content == 'all':
                    print(f"[ERROR] tag+ 不支持 all")
                    return None
                tag_add_set = parse_vlan_set(add_content)
                all_vlan_ids.update(tag_add_set)
            if tag_remove_conf:
                match_r = re.match(r'tag-\[(.*?)\]', tag_remove_conf)
                if not match_r:
                    print(f"[ERROR] tag- 格式错误: {tag_remove_conf}")
                    return None
                rem_content = match_r.group(1).strip()
                if rem_content == 'all':
                    print(f"[ERROR] tag- 不支持 all")
                    return None
                tag_remove_set = parse_vlan_set(rem_content)

            if untag_add_conf:
                match_a = re.match(r'untag\+\[(.*?)\]', untag_add_conf)
                if not match_a:
                    print(f"[ERROR] untag+ 格式错误: {untag_add_conf}")
                    return None
                add_content = match_a.group(1).strip()
                if add_content == 'all':
                    print(f"[ERROR] untag+ 不支持 all")
                    return None
                untag_add_set = parse_vlan_set(add_content)
                all_vlan_ids.update(untag_add_set)
            if untag_remove_conf:
                match_r = re.match(r'untag-\[(.*?)\]', untag_remove_conf)
                if not match_r:
                    print(f"[ERROR] untag- 格式错误: {untag_remove_conf}")
                    return None
                rem_content = match_r.group(1).strip()
                if rem_content == 'all':
                    print(f"[ERROR] untag- 不支持 all")
                    return None
                untag_remove_set = parse_vlan_set(rem_content)

            for gid in group_ids:
                if gid in eth_trunk_configs:
                    # print(eth_trunk_configs)
                    print(f"[ERROR] 聚合组 {gid} 不能同时进行完整配置和增量操作，已跳过该单元格，请重新填写该数据")
                    return None
                if gid not in eth_trunk_increments:
                    eth_trunk_increments[gid] = {
                        "trunk_add": set(), "trunk_remove": set(),
                        "tag_add": set(), "tag_remove": set(),
                        "untag_add": set(), "untag_remove": set()
                    }
                inc = eth_trunk_increments[gid]
                inc["trunk_add"].update(trunk_add_set)
                inc["trunk_remove"].update(trunk_remove_set)
                inc["tag_add"].update(tag_add_set)
                inc["tag_remove"].update(tag_remove_set)
                inc["untag_add"].update(untag_add_set)
                inc["untag_remove"].update(untag_remove_set)
            continue

        # 完整配置（不含增删字段）
        if mode is None:
            print(f"[ERROR] 完整配置必须包含模式字段: {line}")
            return None

        if mode in ('access', 'trunk'):
            if not vlan_conf:
                print(f"[ERROR] {mode}模式必须提供 vlan[内容]")
                return None
            if tag_conf or untag_conf or tag_add_conf or tag_remove_conf or untag_add_conf or untag_remove_conf:
                print(f"[ERROR] {mode}模式不支持 tag/untag")
                return None
        else:  # hybrid
            if not tag_conf and not untag_conf:
                print(f"[ERROR] hybrid模式至少提供 tag 或 untag")
                return None
            if vlan_conf or vlan_add_conf or vlan_remove_conf:
                print(f"[ERROR] hybrid模式不支持 vlan 相关字段")
                return None

        vlan_all_flag = False
        vlan_add_set = set()
        vlan_remove_set = set()
        tag_cmd = None
        untag_cmd = None

        if mode == 'access':
            match_v = re.match(r'vlan\[(.*?)\]', vlan_conf)
            if not match_v:
                print(f"[ERROR] access VLAN配置错误: {vlan_conf}")
                return None
            vlan_num = match_v.group(1).strip()
            if not vlan_num.isdigit():
                print(f"[ERROR] access VLAN必须为数字")
                return None
            all_vlan_ids.add(int(vlan_num))
            vlan_add_set.add(int(vlan_num))
        elif mode == 'trunk':
            match_v = re.match(r'vlan\[(.*?)\]', vlan_conf)
            if not match_v:
                print(f"[ERROR] trunk VLAN配置错误: {vlan_conf}")
                return None
            content = match_v.group(1).strip()
            if content == 'all':
                vlan_all_flag = True
            else:
                vlan_add_set = parse_vlan_set(content)
                all_vlan_ids.update(vlan_add_set)
        elif mode == 'hybrid':
            if tag_conf:
                match_t = re.match(r'tag\[(.*?)\]', tag_conf)
                if not match_t:
                    print(f"[ERROR] tag配置错误: {tag_conf}")
                    return None
                tag_content = match_t.group(1).strip()
                if tag_content == 'all':
                    tag_cmd = "port hybrid tagged vlan 2 to 4094"
                else:
                    tag_cmd = f"port hybrid tagged vlan {tag_content}"
                    all_vlan_ids.update(parse_vlan_set(tag_content))
            if untag_conf:
                match_u = re.match(r'untag\[(.*?)\]', untag_conf)
                if not match_u:
                    print(f"[ERROR] untag配置错误: {untag_conf}")
                    return None
                untag_content = match_u.group(1).strip()
                if untag_content == 'all':
                    untag_cmd = "port hybrid untagged vlan 2 to 4094"
                else:
                    untag_cmd = f"port hybrid untagged vlan {untag_content}"
                    all_vlan_ids.update(parse_vlan_set(untag_content))

        # 存储聚合组完整配置
        for gid in group_ids:
            if gid in eth_trunk_increments:
                print(f"[ERROR] 聚合组 {gid} 不能同时进行完整配置和增量操作")
                return None
            if gid not in eth_trunk_configs:
                eth_trunk_configs[gid] = {
                    "mode": mode,
                    "mode_pvid": mode_pvid,
                    "vlan_all": vlan_all_flag,
                    "vlan_add_set": vlan_add_set,
                    "vlan_remove_set": vlan_remove_set,
                    "tag_cmd": tag_cmd,
                    "untag_cmd": untag_cmd,
                    "edged": edged_flag,
                    "mlag": mlag_flag,
                    "desc": desc_text,
                }
            else:
                existing = eth_trunk_configs[gid]
                if existing["mode"] != mode or existing["mode_pvid"] != mode_pvid:
                    print(f"[ERROR] Eth-Trunk{gid} 模式冲突")
                    return None
                if existing["vlan_all"] and (vlan_add_set or vlan_remove_set):
                    print(f"[ERROR] Eth-Trunk{gid} 已有 all 配置")
                    return None
                if vlan_all_flag and (existing["vlan_add_set"] or existing["vlan_remove_set"]):
                    print(f"[ERROR] Eth-Trunk{gid} 已有具体VLAN")
                    return None
                existing["vlan_all"] = existing["vlan_all"] or vlan_all_flag
                existing["vlan_add_set"].update(vlan_add_set)
                existing["vlan_remove_set"].update(vlan_remove_set)
                if edged_flag:
                    existing["edged"] = True
                if mlag_flag:
                    existing["mlag"] = True
                if desc_text:
                    existing["desc"] = desc_text

        # 物理接口配置
        if interfaces:
            if mode in ('access', 'trunk'):
                match_v = re.match(r'vlan\[(.*?)\]', vlan_conf)
                if not match_v:
                    print(f"[ERROR] VLAN配置格式错误: {vlan_conf}")
                    return None
                vlan_content = match_v.group(1).strip()
                if vlan_content == '':
                    print(f"[ERROR] VLAN配置中括号内为空")
                    return None
                if mode == 'access':
                    if not vlan_content.isdigit():
                        print(f"[ERROR] access模式要求VLAN为单个数字")
                        return None
                    vlan_cmd = f"port default vlan {vlan_content}"
                else:
                    if vlan_content == 'all':
                        vlan_cmd = "port trunk allow-pass vlan 2 to 4094"
                    else:
                        vlan_cmd = f"port trunk allow-pass vlan {vlan_content}"
                tag_cmd = None
                untag_cmd = None
            else:  # hybrid
                vlan_cmd = None
                if tag_conf:
                    match_t = re.match(r'tag\[(.*?)\]', tag_conf)
                    if not match_t:
                        print(f"[ERROR] tag配置格式错误: {tag_conf}")
                        return None
                    tag_content = match_t.group(1).strip()
                    if tag_content == 'all':
                        tag_cmd = "port hybrid tagged vlan 2 to 4094"
                    else:
                        tag_cmd = f"port hybrid tagged vlan {tag_content}"
                else:
                    tag_cmd = None
                if untag_conf:
                    match_u = re.match(r'untag\[(.*?)\]', untag_conf)
                    if not match_u:
                        print(f"[ERROR] untag配置格式错误: {untag_conf}")
                        return None
                    untag_content = match_u.group(1).strip()
                    if untag_content == 'all':
                        untag_cmd = "port hybrid untagged vlan 2 to 4094"
                    else:
                        untag_cmd = f"port hybrid untagged vlan {untag_content}"
                else:
                    untag_cmd = None

            # 生成每个接口的描述列表
            if desc_text:
                descs = expand_description_for_interfaces(desc_text, interfaces)
            else:
                descs = [None] * len(interfaces)
            # 处理未分组的物理接口
            if not group_ids:
                for i, iface in enumerate(interfaces):
                    if iface in interface_bindings:
                        existing = interface_bindings[iface]
                        if desc_text:
                            existing["desc"] = descs[i] if descs and i < len(descs) else None
                        if port_mode and existing.get("port_mode") != port_mode:
                            print(f"[ERROR] 物理接口 {iface} 的 port 模式冲突")
                            return None
                        continue
                    interface_bindings[iface] = {
                        "group_id": None,
                        "mode": mode,
                        "mode_pvid": mode_pvid,
                        "vlan_cmd": vlan_cmd,
                        "tag_cmd": tag_cmd,
                        "untag_cmd": untag_cmd,
                        "edged": edged_flag,
                        "port_mode": port_mode,
                        "desc": descs[i] if descs and i < len(descs) else None,
                    }
            else:
                if len(group_ids) == 1:
                    single_gid = group_ids[0]
                    for i, iface in enumerate(interfaces):
                        if iface in interface_bindings:
                            existing = interface_bindings[iface]
                            if desc_text:
                                existing["desc"] = descs[i] if descs and i < len(descs) else None
                            if port_mode and existing.get("port_mode") != port_mode:
                                print(f"[ERROR] 物理接口 {iface} 的 port 模式冲突")
                                return None
                            continue
                        interface_bindings[iface] = {
                            "group_id": single_gid,
                            "mode": mode,
                            "mode_pvid": mode_pvid,
                            "vlan_cmd": None,
                            "tag_cmd": None,
                            "untag_cmd": None,
                            "edged": edged_flag,
                            "port_mode": port_mode,
                            "desc": descs[i] if descs and i < len(descs) else None,
                        }
                else:
                    if len(interfaces) != len(group_ids):
                        print(f"[ERROR] 接口数量与聚合组数量不匹配")
                        return None
                    for i, (iface, gid) in enumerate(zip(interfaces, group_ids)):
                        if iface in interface_bindings:
                            existing = interface_bindings[iface]
                            if desc_text:
                                existing["desc"] = descs[i] if descs and i < len(descs) else None
                            if port_mode and existing.get("port_mode") != port_mode:
                                print(f"[ERROR] 物理接口 {iface} 的 port 模式冲突")
                                return None
                            continue
                        interface_bindings[iface] = {
                            "group_id": gid,
                            "mode": mode,
                            "mode_pvid": mode_pvid,
                            "vlan_cmd": None,
                            "tag_cmd": None,
                            "untag_cmd": None,
                            "edged": edged_flag,
                            "port_mode": port_mode,
                            "desc": descs[i] if descs and i < len(descs) else None,
                        }

    # 第二遍：应用外部描述列
    for desc_line in desc_lines:
        parsed = parse_description_line(desc_line)
        if not parsed:
            continue
        target_type, target_list, desc_template = parsed
        if target_type == 'group':
            for gid in target_list:
                if gid in eth_trunk_configs and not eth_trunk_configs[gid].get('desc'):
                    eth_trunk_configs[gid]['desc'] = desc_template
        elif target_type == 'interface':
            descs = expand_description_for_interfaces(desc_template, target_list)
            for iface, desc in zip(target_list, descs):
                if iface in interface_bindings and not interface_bindings[iface].get('desc'):
                    interface_bindings[iface]['desc'] = desc


    # ---------- 生成各部分配置（使用模板） ----------
    vlan_batch_lines = []
    if all_vlan_ids:
        vlan_batch_lines = format_vlan_batch_lines(all_vlan_ids, MAX_GROUPS_PER_LINE)

    eth_trunk_lines = []
    # 收集所有涉及的聚合组编号并排序
    all_gids = sorted(set(eth_trunk_configs.keys()) | set(eth_trunk_increments.keys()))
    for gid in all_gids:
        # 1. 如果存在完整配置，先生成
        if gid in eth_trunk_configs:
            cfg = eth_trunk_configs[gid]
            interface = f"Eth-Trunk{gid}"
            edged = " stp edged-port enable\n" if cfg["edged"] else ""
            mlag = f" dfs-group 1 m-lag {gid}\n" if cfg["mlag"] else ""
            desc = f" description {cfg['desc']}\n" if cfg.get("desc") else ""

            if cfg["mode"] == 'access':
                vlan = list(cfg["vlan_add_set"])[0] if cfg["vlan_add_set"] else ''
                block = ETH_TRUNK_ACCESS_TEMPLATE.format(
                    interface=interface,
                    vlan=vlan,
                    edged=edged,
                    mlag=mlag,
                    desc=desc
                )
            elif cfg["mode"] == 'trunk':
                pvid = f" port trunk pvid vlan {cfg['mode_pvid']}\n" if cfg["mode_pvid"] is not None else ""
                if cfg["vlan_all"]:
                    base_set = set(range(2, 4095))
                    final_set = (base_set - cfg["vlan_remove_set"]) | cfg["vlan_add_set"]
                else:
                    final_set = cfg["vlan_add_set"] - cfg["vlan_remove_set"]
                final_set.discard(1)
                allow = ""
                if final_set:
                    vlan_range_str = format_vlan_range_string(final_set)
                    if vlan_range_str:
                        allow = f" port trunk allow-pass vlan {vlan_range_str}\n"
                remove = ""
                if cfg["vlan_remove_set"] and not cfg["vlan_all"]:
                    remove_range = format_vlan_range_string(cfg["vlan_remove_set"])
                    if remove_range:
                        remove = f" undo port trunk allow-pass vlan {remove_range}\n"
                block = ETH_TRUNK_TRUNK_TEMPLATE.format(
                    interface=interface,
                    pvid=pvid,
                    allow=allow,
                    remove=remove,
                    edged=edged,
                    mlag=mlag,
                    desc=desc
                )
            else:  # hybrid
                pvid = f" port hybrid pvid vlan {cfg['mode_pvid']}\n" if cfg["mode_pvid"] is not None else ""
                tag = f" {cfg['tag_cmd']}\n" if cfg.get("tag_cmd") else ""
                untag = f" {cfg['untag_cmd']}\n" if cfg.get("untag_cmd") else ""
                block = ETH_TRUNK_HYBRID_TEMPLATE.format(
                    interface=interface,
                    pvid=pvid,
                    tag=tag,
                    untag=untag,
                    edged=edged,
                    mlag=mlag,
                    desc=desc
                )
            eth_trunk_lines.append(block)

        # 2. 如果存在增量配置，再生成
        if gid in eth_trunk_increments:

            inc = eth_trunk_increments[gid]
            cmds = []
            if inc["trunk_add"]:
                add_range = format_vlan_range_string(inc["trunk_add"])
                if add_range:
                    cmds.append(f" port trunk allow-pass vlan {add_range}")
            if inc["trunk_remove"]:
                rem_range = format_vlan_range_string(inc["trunk_remove"])
                if rem_range:
                    cmds.append(f" undo port trunk allow-pass vlan {rem_range}")
            if inc["tag_add"]:
                add_range = format_vlan_range_string(inc["tag_add"])
                if add_range:
                    cmds.append(f" port hybrid tagged vlan {add_range}")
            if inc["tag_remove"]:
                rem_range = format_vlan_range_string(inc["tag_remove"])
                if rem_range:
                    cmds.append(f" undo port hybrid tagged vlan {rem_range}")
            if inc["untag_add"]:
                add_range = format_vlan_range_string(inc["untag_add"])
                if add_range:
                    cmds.append(f" port hybrid untagged vlan {add_range}")
            if inc["untag_remove"]:
                rem_range = format_vlan_range_string(inc["untag_remove"])
                if rem_range:
                    cmds.append(f" undo port hybrid untagged vlan {rem_range}")
            if cmds:
                block = ETH_TRUNK_INCREMENT_TEMPLATE.format(
                    interface=f"Eth-Trunk{gid}",
                    commands="\n".join(cmds)
                )
                eth_trunk_lines.append(block)

    # 物理接口排序生成
    def interface_sort_key(iface):
        rate_match = re.search(r'^(\d+)', iface)
        rate = int(rate_match.group(1)) if rate_match else 0
        parts = iface.split('/')
        if len(parts) >= 3:
            slot_part = parts[0]
            slot_match = re.search(r'(\d+)$', slot_part)
            slot = int(slot_match.group(1)) if slot_match else 0
            subslot = int(parts[1]) if parts[1].isdigit() else 0
            port = int(parts[2]) if parts[2].isdigit() else 0
        else:
            slot = subslot = port = 0
        return (rate, slot, subslot, port)

    physical_lines = []
    for iface in sorted(interface_bindings.keys(), key=interface_sort_key):
        
        bind = interface_bindings[iface]
        port_mode = f" port mode {bind['port_mode']}\n" if bind.get("port_mode") else ""
        edged = f" stp edged-port enable\n" if bind["edged"] else ""
        desc = f" description {bind['desc']}\n" if bind.get("desc") else ""

        if bind["group_id"] is not None:
            edged = ""   # 若物理口绑定了聚合组，则强制置空
            block = PHYSICAL_BUNDLE_TEMPLATE.format(
                interface=iface,
                port_mode=port_mode,
                group=bind["group_id"],
                edged=edged,
                desc=desc
            )
        else:
            if bind["mode"] == 'access':
                block = PHYSICAL_ACCESS_TEMPLATE.format(
                    interface=iface,
                    port_mode=port_mode,
                    vlan=bind['vlan_cmd'].split()[-1],
                    edged=edged,
                    desc=desc
                )
            elif bind["mode"] == 'trunk':
                pvid = f" port trunk pvid vlan {bind['mode_pvid']}\n" if bind["mode_pvid"] is not None else ""
                # 与前导空格保持一致，否则该命令渲染后会顶格
                allow = " " + bind['vlan_cmd'] + "\n"
                block = PHYSICAL_TRUNK_TEMPLATE.format(
                    interface=iface,
                    port_mode=port_mode,
                    pvid=pvid,
                    allow=allow,
                    edged=edged,
                    desc=desc
                )
            else:  # hybrid
                pvid = f" port hybrid pvid vlan {bind['mode_pvid']}\n" if bind["mode_pvid"] is not None else ""
                tag = f" {bind['tag_cmd']}\n" if bind.get("tag_cmd") else ""
                untag = f" {bind['untag_cmd']}\n" if bind.get("untag_cmd") else ""
                block = PHYSICAL_HYBRID_TEMPLATE.format(
                    interface=iface,
                    port_mode=port_mode,
                    pvid=pvid,
                    tag=tag,
                    untag=untag,
                    edged=edged,
                    desc=desc
                )
        physical_lines.append(block)
    
    return {
        "vlan_batch": vlan_batch_lines,
        "eth_trunks": eth_trunk_lines,
        "physicals": physical_lines,
        "eth_trunk_details": eth_trunk_configs,       # 完整配置的聚合组
        "eth_trunk_increments": eth_trunk_increments, # 增量操作的聚合组
        "bound_groups": set(
            bind["group_id"] for bind in interface_bindings.values()
            if bind.get("group_id") is not None
        ),
        "interface_bindings": interface_bindings,     # 所有物理接口绑定信息
        "all_vlan_ids": all_vlan_ids,
    }

# ===================== 业务网关解析 ======================

def parse_vlanif_config(cell_value, desc_cell):
    if not cell_value or not isinstance(cell_value, str):
        return None

    vpn_instances = defaultdict(list)
    vlanif_configs = {}

    # 1. 解析网关行
    for line in cell_value.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # 匹配格式：vlanif<范围>_vpn[<vpn>]_ip[<ip>]
        m = re.match(r'vlanif(\d+(?:-\d+)?)(?:_vpn\[(.*?)\])?_ip\[(.*?)\]', line, re.IGNORECASE)
        if not m:
            print(f"[WARN] 业务网关格式错误: {line}")
            continue

        vlan_range_str = m.group(1)
        vpn = m.group(2) if m.group(2) is not None else ''
        ip_expr = m.group(3).strip()

        vlan_ids = expand_vlan_range(vlan_range_str)
        ip_list = expand_ip_range(ip_expr)

        # 检查数量匹配
        if len(ip_list) != len(vlan_ids):
            if len(ip_list) == 1:
                # 允许单 IP 复用给所有 VLAN
                ip_list = ip_list * len(vlan_ids)
            else:
                print(f"[ERROR] VLAN 数量 ({len(vlan_ids)}) 与 IP 数量 ({len(ip_list)}) 不匹配，行: {line}")
                continue

        for vlan_id, ip in zip(vlan_ids, ip_list):
            if vlan_id in vlanif_configs:
                # 若已存在，检查 VPN/IP 是否一致，不一致则报错
                existing = vlanif_configs[vlan_id]
                if existing['vpn'] != vpn or existing['ip'] != ip:
                    print(f"[ERROR] Vlanif{vlan_id} 配置冲突: {existing} vs {{vpn:{vpn}, ip:{ip}}}")
                    continue
            else:
                vlanif_configs[vlan_id] = {'vpn': vpn, 'ip': ip, 'desc': None}
            if vpn:
                vpn_instances[vpn].append(vlan_id)

    # 2. 解析描述列（如果有）
    if desc_cell and isinstance(desc_cell, str):
        for line in desc_cell.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r'vlanif(\d+(?:-\d+)?)_desc\[(.*?)\]', line, re.IGNORECASE)
            if m:
                vlan_range_str = m.group(1)
                desc = m.group(2).strip()
                vlan_ids = expand_vlan_range(vlan_range_str)
                for vlan_id in vlan_ids:
                    if vlan_id in vlanif_configs:
                        vlanif_configs[vlan_id]['desc'] = desc
                    else:
                        # 描述行可能在网关行之前出现，但一般要求先有网关数据，此处略过或可补充默认配置
                        print(f"[WARN] 描述对应的 Vlanif{vlan_id} 未在网关列定义，忽略")
            else:
                print(f"[WARN] 描述格式错误: {line}")

    # 去重排序
    for vpn in vpn_instances:
        vpn_instances[vpn] = sorted(set(vpn_instances[vpn]))

    all_vlan_ids = set(vlanif_configs.keys())
    return {
        "vpn_instances": vpn_instances,
        "vlanif_configs": vlanif_configs,
        "all_vlan_ids": all_vlan_ids, 
    }

def generate_vpn_instance_config(device_name, vpn_instances, device_map, vrf_subint_map):
    if not vpn_instances:
        return None

    dev_info = device_map.get(device_name, {})
    as_number = dev_info.get('as', DEFAULT_AS) if isinstance(dev_info, dict) else DEFAULT_AS

    blocks = []
    for vpn in sorted(vpn_instances.keys()):
        vrf_id = vrf_subint_map.get(vpn, DEFAULT_VRF_SUBINT)
        rd = f"{as_number}:{vrf_id}"
        blocks.append(VRF_TEMPLATE.format(vrf=vpn, rd=rd))
    return "\n".join(blocks) if blocks else None

def generate_vlanif_config(vlanif_configs):
    if not vlanif_configs:
        return None
    blocks = []
    for vlan_id in sorted(vlanif_configs.keys()):
        cfg = vlanif_configs[vlan_id]
        # 若ip不带/，则默认使用掩码
        if '/' not in cfg['ip']:
            ip_addr = cfg['ip']
            netmask = VLANIF_DEFAULT_GATEWAY_MASK
        else:
            ip_addr, netmask = cidr_to_address_mask(cfg['ip'])

        vpn_binding = f" ip binding vpn-instance {cfg['vpn']}\n" if cfg.get('vpn') else ""
        desc = f" description {cfg['desc']}\n" if cfg.get('desc') else ""
        blocks.append(VLANIF_TEMPLATE.format(
            vlan_id=vlan_id,
            vpn_binding=vpn_binding,
            ip_address=ip_addr,
            netmask=netmask,
            mac=VLANIF_DEFAULT_MAC_ADDRESS,
            desc=desc
        ))
    return "\n".join(blocks)

# ===================== 插入函数（有基线场景） ======================

def insert_vlan_block_into_baseline(baseline, vlan_batch_lines):
    if not vlan_batch_lines:
        return baseline
    # 构建块：vlan batch 命令 + 结尾 #，并确保末尾换行
    block_lines = vlan_batch_lines 
    block = "\n".join(block_lines) + "\n"
    lines = baseline.splitlines(keepends=True)
    # 找到第一个 stp 行
    stp_idx = -1
    for i, line in enumerate(lines):
        if line.strip().lower().startswith('stp'):
            stp_idx = i
            break
    if stp_idx == -1:
        # 没有 stp，追加到末尾
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(block)
        return ''.join(lines)
    # 在 stp 行之前插入
    insert_pos = stp_idx
    # 确保插入位置前有换行
    if insert_pos > 0 and not lines[insert_pos-1].endswith('\n'):
        lines.insert(insert_pos, '\n')
        insert_pos += 1
    lines.insert(insert_pos, block)
    return ''.join(lines)

def insert_vpn_block_into_baseline(baseline, vpn_block):
    if not vpn_block:
        return baseline
    if not vpn_block.endswith('\n'):
        vpn_block += '\n'
    # 确保尾部有单独的 # 行
    if not vpn_block.strip().endswith('#'):
        vpn_block = vpn_block.rstrip('\n') + '\n#\n'
    else:
        if not vpn_block.endswith('#\n'):
            vpn_block = vpn_block.rstrip('\n') + '\n'
    lines = baseline.splitlines(keepends=True)
    acl_idx = -1
    for i, line in enumerate(lines):
        if line.strip().lower().startswith('acl'):
            acl_idx = i
            break
    if acl_idx == -1:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(vpn_block)
        return ''.join(lines)
    insert_pos = acl_idx
    if insert_pos > 0 and not lines[insert_pos-1].endswith('\n'):
        lines.insert(insert_pos, '\n')
        insert_pos += 1
    lines.insert(insert_pos, vpn_block)
    return ''.join(lines)

def insert_vlanif_block_into_baseline(baseline, vlanif_block):
    if not vlanif_block:
        return baseline
    if not vlanif_block.endswith('\n'):
        vlanif_block += '\n'
    if not vlanif_block.strip().endswith('#'):
        vlanif_block = vlanif_block.rstrip('\n') + '\n#\n'
    else:
        if not vlanif_block.endswith('#\n'):
            vlanif_block = vlanif_block.rstrip('\n') + '\n'
    lines = baseline.splitlines(keepends=True)
    meth_idx = -1
    for i, line in enumerate(lines):
        if line.strip().lower().startswith('interface meth'):
            meth_idx = i
            break
    if meth_idx == -1:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(vlanif_block)
        return ''.join(lines)
    insert_pos = meth_idx
    if insert_pos > 0 and not lines[insert_pos-1].endswith('\n'):
        lines.insert(insert_pos, '\n')
        insert_pos += 1
    lines.insert(insert_pos, vlanif_block)
    return ''.join(lines)

def insert_eth_trunk_block_into_baseline(baseline, eth_block):
    if not eth_block:
        return baseline
    if not eth_block.endswith('\n'):
        eth_block += '\n'
    lines = baseline.splitlines(keepends=True)
    trunk0_end = -1
    for i, line in enumerate(lines):
        if line.strip().lower().startswith('interface eth-trunk0'):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith('interface'):
                j += 1
            trunk0_end = j
            break
    if trunk0_end != -1:
        insert_pos = trunk0_end
    else:
        for i, line in enumerate(lines):
            if line.strip().lower().startswith('interface') and not re.search(r'eth-trunk', line, re.I):
                insert_pos = i
                break
        else:
            insert_pos = len(lines)
    if insert_pos > 0 and not lines[insert_pos-1].endswith('\n'):
        lines.insert(insert_pos, '\n')
        insert_pos += 1
    lines.insert(insert_pos, eth_block)
    return ''.join(lines)

def merge_physical_into_baseline(baseline, physical_lines): 
    if not physical_lines:
        return baseline
    for block in physical_lines:
        # print(block)
        # if not block.strip():
        #     continue
        # first_line = block.splitlines()[0]
        lines = [line for line in block.splitlines() if line.strip()]   # 过滤掉空行和仅含空格的行 
        if not lines:                    # 如果过滤后为空，跳过
            continue
        block = '\n'.join(lines)        # 重新拼接成无空行的字符串
        first_line = lines[0]           # 取第一行
        # print(first_line)
        m = re.match(r'interface\s+(\S+)', first_line, re.I)
        if not m:
            continue
        iface = m.group(1)
        # print(iface)
        pattern = rf'^interface\s+{re.escape(iface)}\s*$(?:\n.*?)^#$'
        # print(pattern)
        found = re.search(pattern, baseline, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        # print(found)
        
        if found:
            
            base_block = found.group(0)
            # print(base_block)
            base_lines = base_block.splitlines()
            # 只做过滤、不做 strip：保留原行的前导空格，输出时才不会丢缩进
            base_cmds = [ln for ln in base_lines[1:-1]
                         if ln.strip() and not ln.strip().lower().startswith('interface')]
            new_lines = block.splitlines()
            new_cmds = [ln for ln in new_lines[1:]
                        if ln.strip() and not ln.strip().lower().startswith('interface')
                        and ln.strip() != '#']

            def _norm_cmd(line):
                """保证命令行至少有一个前导空格，且用于去重时忽略缩进差异"""
                s = line.strip()
                return (' ' + s) if (s and not line[:1].isspace()) else line

            merged_cmds = []
            existing_set = set()          # 去重用的规范化命令（去掉缩进）
            for cmd in base_cmds:
                key = cmd.strip()
                if key.lower() == 'shutdown':
                    continue
                if key in existing_set:
                    continue
                merged_cmds.append(_norm_cmd(cmd))
                existing_set.add(key)
            for cmd in new_cmds:
                key = cmd.strip()
                if key.lower() == 'shutdown':
                    continue
                if key in existing_set:
                    continue
                merged_cmds.append(_norm_cmd(cmd))
                existing_set.add(key)
            new_block_lines = [base_lines[0]] + merged_cmds + ['#']
            new_block = '\n'.join(new_block_lines)
            baseline = baseline.replace(base_block, new_block, 1)
        else:
            if not baseline.endswith('\n'):
                baseline += '\n'
            baseline += block + '\n'
    return baseline


# ===================== 回退脚本生成 ======================
def generate_rollback_script(local_sysname, vlan_config, gw_config, device_map, vrf_subint_map, all_vlan_ids=None):
    """
    生成回退脚本内容（仅用于无基线场景）
    """
    lines = []
    lines.append(local_sysname)
    lines.append("#")
    lines.append("system")
    lines.append("#")

    # 1. undo VPN 实例
    if gw_config and gw_config.get("vpn_instances"):
        for vpn in sorted(gw_config["vpn_instances"].keys()):
            lines.append(f"undo ip vpn-instance {vpn}")
        lines.append("#")

    # 2. 物理接口 clear configuration + shutdown
    if vlan_config and vlan_config.get("interface_bindings"):
        # 按接口名排序（便于阅读）
        for iface in sorted(vlan_config["interface_bindings"].keys()):
            lines.append(f"interface {iface}")
            lines.append(" clear configuration this")
            lines.append(" y")
            lines.append(" shutdown")
        lines.append("#")

    # 3. 聚合组处理
    if vlan_config:
        # 获取所有聚合组（完整配置 + 增量）
        all_groups = set(vlan_config.get("eth_trunk_details", {}).keys()) | \
                     set(vlan_config.get("eth_trunk_increments", {}).keys())
        bound_groups = vlan_config.get("bound_groups", set())

        for gid in sorted(all_groups):
            # 判断是否有完整配置
            has_full = gid in vlan_config["eth_trunk_details"]
            # 判断是否被绑定
            is_bound = gid in bound_groups

            if has_full and is_bound:
                # 完整配置且被绑定 → 直接 undo interface
                lines.append(f"undo interface Eth-Trunk{gid}")
            elif has_full and not is_bound:
                # 完整配置但未被绑定 → 进入接口逐条删除所有配置
                cfg = vlan_config["eth_trunk_details"][gid]
                lines.append(f"interface Eth-Trunk{gid}")
                # 根据模式生成对应的 undo 命令
                if cfg["mode"] == "access":
                    lines.append(" undo port link-type")
                    # 如果有 default vlan，添加 undo
                    if cfg.get("vlan_add_set"):
                        lines.append(" undo port default vlan")
                elif cfg["mode"] == "trunk":
                    # undo pvid
                    if cfg.get("mode_pvid") is not None:
                        lines.append(" undo port trunk pvid vlan")
                    # undo allow-pass
                    if cfg.get("vlan_all"):
                        # 如果允许了所有 VLAN，生成删除所有
                        lines.append(" undo port trunk allow-pass vlan 2 to 4094")
                    else:
                        vlan_set = cfg.get("vlan_add_set", set()) - cfg.get("vlan_remove_set", set())
                        if vlan_set:
                            vlan_range = format_vlan_range_string(vlan_set)
                            if vlan_range:
                                lines.append(f" undo port trunk allow-pass vlan {vlan_range}")
                    lines.append(" undo port link-type")
                elif cfg["mode"] == "hybrid":
                    # undo pvid
                    if cfg.get("mode_pvid") is not None:
                        lines.append(" undo port hybrid pvid vlan")
                    # undo tagged
                    if cfg.get("tag_cmd"):
                        # 提取 VLAN 范围
                        match = re.search(r'vlan\s+(.+)', cfg["tag_cmd"])
                        if match:
                            lines.append(f" undo port hybrid tagged vlan {match.group(1)}")
                    # undo untagged
                    if cfg.get("untag_cmd"):
                        match = re.search(r'vlan\s+(.+)', cfg["untag_cmd"])
                        if match:
                            lines.append(f" undo port hybrid untagged vlan {match.group(1)}")
                    lines.append(" undo port link-type")
                # 如果存在 mlag 或 edged 配置，也可以添加 undo（但通常 clear 后会消失，此处可略）
                lines.append("#")
            elif not has_full and gid in vlan_config["eth_trunk_increments"]:
                # 仅有增量操作 → 只撤销增量命令
                inc = vlan_config["eth_trunk_increments"][gid]
                lines.append(f"interface Eth-Trunk{gid}")
                # 撤销 trunk 增量
                if inc.get("trunk_add"):
                    vlan_range = format_vlan_range_string(inc["trunk_add"])
                    if vlan_range:
                        lines.append(f" undo port trunk allow-pass vlan {vlan_range}")
                if inc.get("trunk_remove"):
                    # 注意：撤销移除实际上是要添加回来，但回退时应恢复，所以这里应该重新添加？但我们无法知道之前的状态。
                    # 对于回退脚本，我们只撤销本次添加的命令，而 "trunk_remove" 是删除操作，回退时应重新添加。
                    # 但更简单的是：我们只撤销添加操作，因为移除操作是删除，回退应该恢复，但恢复需要知道之前存在的VLAN，我们不知道。
                    # 因此，我们只处理添加操作，对于移除，我们不做逆向，而是建议不处理，因为移除可能不是本次添加的。
                    # 为了稳妥，我们不对 trunk_remove 生成 undo，因为 undo 是删除，但我们可以生成添加命令。
                    # 但这样会导致回退脚本添加回被删除的VLAN，可能引起问题。
                    # 根据用户需求，回退脚本应撤销本次配置，所以我们只撤销我们添加的，不撤销我们移除的（因为移除是删除，我们不应该重新添加）。
                    # 所以此处仅处理 add，忽略 remove。
                    pass
                # 撤销 hybrid 增量
                if inc.get("tag_add"):
                    vlan_range = format_vlan_range_string(inc["tag_add"])
                    if vlan_range:
                        lines.append(f" undo port hybrid tagged vlan {vlan_range}")
                if inc.get("untag_add"):
                    vlan_range = format_vlan_range_string(inc["untag_add"])
                    if vlan_range:
                        lines.append(f" undo port hybrid untagged vlan {vlan_range}")
                # 对于 remove 操作，同样忽略（回退时不恢复）
                lines.append("#")
        lines.append("#")

    # 4. undo Vlanif 接口
    if gw_config and gw_config.get("vlanif_configs"):
        for vlan_id in sorted(gw_config["vlanif_configs"].keys()):
            lines.append(f"undo interface Vlanif{vlan_id}")
        lines.append("#")

    # 5. undo VLAN（撤销本次创建的 VLAN），按 MAX_GROUPS_PER_LINE 分组
    if all_vlan_ids:
        groups = compress_vlan_set_to_groups(all_vlan_ids)
        if groups:
            for i in range(0, len(groups), MAX_GROUPS_PER_LINE):
                group_str = " ".join(groups[i:i+MAX_GROUPS_PER_LINE])
                lines.append(f"undo vlan batch {group_str}")
            lines.append("#")

    lines.append("commit")
    return "\n".join(lines)

# ===================== 主函数 ======================

def main(excel_file, sheet_name, output_dir, rollback_dir, template_dir, global_device_info):
    print("="*60)
    if not os.path.isfile(excel_file):
        print(f"错误：Excel文件 '{excel_file}' 不存在")
        sys.exit(1)
    if not os.path.isdir(template_dir):
        print(f"错误：模板目录 '{template_dir}' 不存在")
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)
    print(f"开始处理Sheet: {sheet_name}")
    wb = load_workbook(excel_file, data_only=True)
    if sheet_name:
        if sheet_name not in wb.sheetnames:
            print(f"错误：工作表 '{sheet_name}' 不存在")
            sys.exit(1)
        sheet = wb[sheet_name]
    else:
        sheet = wb.active

    device_map, vrf_subint_map = load_device_mapping(global_device_info)

    var_to_col = get_column_indices(sheet, COLUMN_MAPPING)
    devices = read_device_data(sheet, var_to_col)
    if not devices:
        print("警告：Excel中没有有效设备数据")
        sys.exit(0)

    success_count = 0
    skip_count = 0
    rollback_count = 0



    for idx, device in enumerate(devices, start=2):
        local_sysname = device.get('<local_sysname>', '')
        template_name = device.get('<template_name>', '')
        int_vlan_raw = device.get('<int_vlan>', '')
        int_desc_raw = device.get('<int_desc>', '')
        vlanif_gw_raw = device.get('<vlanif_gw>', '')
        vlanif_desc_raw = device.get('<vlanif_desc>', '')

        has_template = bool(template_name)
        has_int_vlan = bool(int_vlan_raw)
        has_vlanif_gw = bool(vlanif_gw_raw)

        generate_base = has_template
        generate_vlan = has_int_vlan
        generate_gw = has_vlanif_gw

        if not (generate_base or generate_vlan or generate_gw):
            continue

        # 处理基线
        if generate_base:
            if not template_name.endswith('.txt'):
                template_name += '.txt'
            template_path = os.path.join(template_dir, template_name)
            if not os.path.isfile(template_path):
                print(f"'{local_sysname}' 模板文件 '{template_path}' 不存在，跳过")
                skip_count += 1
                continue
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_content = f.read()
            except Exception as e:
                print(f"读取模板失败: {e}")
                skip_count += 1
                continue
            replacements = {var: device.get(var, '') for var in var_to_col.keys() if var != '<template_name>'}
            output_content = replace_template(template_content, replacements)
            stp_root_mac = device.get('<stp_root_mac>', '')
            if stp_root_mac:
                if re.match(r'^[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}$', stp_root_mac):
                    output_content = insert_stp_root_commands(output_content, stp_root_mac)
                else:
                    print(f"STP根桥MAC格式不正确: {stp_root_mac}")
        else:
            output_content = ""

        # 解析接口VLAN配置（传入描述列）
        vlan_config = None
        if generate_vlan:
            vlan_config = parse_interface_config(int_vlan_raw, int_desc_raw)
            if vlan_config is None:
                print(f"'{local_sysname}' 业务VLAN解析失败，跳过该部分")

        # 解析业务网关
        gw_config = None
        if generate_gw:
            gw_config = parse_vlanif_config(vlanif_gw_raw, vlanif_desc_raw)
            if gw_config is None:
                print(f"'{local_sysname}' 业务网关解析失败，跳过该部分")

        vpn_block = None
        vlanif_block = None
        if gw_config:
            vpn_block = generate_vpn_instance_config(
                local_sysname,
                gw_config['vpn_instances'],
                device_map,
                vrf_subint_map
            )
            vlanif_block = generate_vlanif_config(gw_config['vlanif_configs'])

        # 生成安全文件名
        safe_name = "".join(c for c in local_sysname if c.isalnum() or c in ('-', '_')).rstrip()
        if not safe_name:
            safe_name = f'safename_{idx}'
        file_name = f"{safe_name}.txt"

        # ---------- 按有无基线组织最终内容 ----------
        if not generate_base:
            # ---- 合并所有 VLAN ID ----
            all_vlan_ids = set()
            if vlan_config and vlan_config.get('all_vlan_ids'):
                all_vlan_ids.update(vlan_config['all_vlan_ids'])
            if gw_config and gw_config.get('all_vlan_ids'):
                all_vlan_ids.update(gw_config['all_vlan_ids'])
            vlan_batch_lines = format_vlan_batch_lines(all_vlan_ids, MAX_GROUPS_PER_LINE) if all_vlan_ids else []

            # ---- 构建正向脚本 ----
            parts = []
            if local_sysname:
                parts.append(f"{local_sysname} \n\n#\nsystem\n#")
            if vlan_batch_lines:
                parts.append("\n".join(vlan_batch_lines))
            if vpn_block:
                parts.append(vpn_block)
            if vlanif_block:
                parts.append(vlanif_block)
            if vlan_config:
                if vlan_config['eth_trunks']:
                    parts.append("\n".join(vlan_config['eth_trunks']))
                if vlan_config['physicals']:
                    parts.append("\n".join(vlan_config['physicals']))
            parts.append("commit\n\n")
            output_content = "\n".join(parts)

            # ---- 生成回退脚本 ----
            rollback_content = generate_rollback_script(
                local_sysname,
                vlan_config,
                gw_config,
                device_map,
                vrf_subint_map,
                all_vlan_ids=all_vlan_ids
            )
            os.makedirs(rollback_dir, exist_ok=True)
            rollback_file = os.path.join(rollback_dir, f"回退脚本_{safe_name}.txt")
            with open(rollback_file, 'w', encoding='utf-8') as f:
                f.write(rollback_content)
            print(f"已生成回退脚本 {rollback_file}")
            rollback_count += 1
                
        else:
            # ---- 有基线分支 ----
            # 同样合并所有 VLAN ID
            all_vlan_ids = set()
            if vlan_config and vlan_config.get('all_vlan_ids'):
                all_vlan_ids.update(vlan_config['all_vlan_ids'])
            if gw_config and gw_config.get('all_vlan_ids'):
                all_vlan_ids.update(gw_config['all_vlan_ids'])
            vlan_batch_lines = format_vlan_batch_lines(all_vlan_ids, MAX_GROUPS_PER_LINE) if all_vlan_ids else []

            # 插入 vlan block（使用合并后的）
            if vlan_batch_lines:
                output_content = insert_vlan_block_into_baseline(output_content, vlan_batch_lines)
            if vpn_block:
                output_content = insert_vpn_block_into_baseline(output_content, vpn_block)
            if vlanif_block:
                output_content = insert_vlanif_block_into_baseline(output_content, vlanif_block)
            if vlan_config and vlan_config['eth_trunks']:
                eth_block = "\n".join(vlan_config['eth_trunks'])
                output_content = insert_eth_trunk_block_into_baseline(output_content, eth_block)
            if vlan_config and vlan_config['physicals']:
                physical_lines = vlan_config['physicals']
                output_content = merge_physical_into_baseline(output_content, physical_lines)

        output_content = remove_empty_lines(output_content)

        output_path = os.path.join(output_dir, file_name)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output_content)
        print(f"已生成变更脚本 {output_path} ")
        success_count += 1
        

    print(f"\n共生成 {success_count} 个变更脚本，共 {rollback_count} 个回退脚本，跳过 {skip_count} 个设备")
    print("="*60)

if __name__ == '__main__':
    main(EXCEL_PATH, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, TEMPLATE_DIR, GLOBAL_DEVICE_INFO)