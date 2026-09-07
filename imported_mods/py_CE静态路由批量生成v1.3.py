import pandas as pd
import os
import ipaddress


# ====== 用户自定义配置区 ======
EXCEL_FILE = "excel_CE静态路由批量生成v1.3.xlsx"
OUTPUT_DIR = "output"
SHEET_NAME = "仅静态路由场景"
ROLLBACK_DIR = os.path.join(OUTPUT_DIR, "回退脚本")
# ---------- 工具函数 ----------
def get_clean_str(row, col_name):
    """
    安全地从行中获取指定列的值，去除首尾空格。
    若值为 NaN 或 None，返回空字符串。
    """
    val = row.get(col_name, '')
    if pd.isna(val):
        return ''
    return str(val).strip()

def parse_dest(dest_str):
    """
    解析'目的地址/掩码'，自动识别 IPv4 或 IPv6。
    返回 (原始IP地址, 掩码表示, 版本号)
    - IPv4 掩码为点分十进制，如 '255.255.255.0'
    - IPv6 掩码为前缀长度，如 '64'
    若格式错误，抛出 ValueError
    """
    try:
        iface = ipaddress.ip_interface(dest_str)
        ip = str(iface.ip)
        version = iface.version
        if version == 4:
            mask = str(iface.netmask)          # 点分十进制
        else:  # IPv6
            mask = str(iface.network.prefixlen) # 前缀长度
        return ip, mask, version
    except ValueError as e:
        raise ValueError(f"无效的目的地址格式: {e}")

def build_command(src_vpn, ip, mask, dest_vpn, nexthop, priority, desc, version=4):
    """
    根据各参数构建一条完整的静态路由命令字符串。
    version: 4 或 6，决定使用 ip route-static 还是 ipv6 route-static
    """
    parts = []
    if version == 6:
        parts.append("ipv6 route-static")
    else:
        parts.append("ip route-static")
    if src_vpn:
        parts.append(f"vpn-instance {src_vpn}")
    parts.append(ip)
    parts.append(mask)   # IPv4 为点分十进制，IPv6 为前缀长度

    if dest_vpn:
        parts.append(f"vpn-instance {dest_vpn}")

    if nexthop:
        parts.append(nexthop)

    if priority:
        parts.append(f"preference {priority}")
    if desc:
        parts.append(f"description {desc}")

    return " ".join(parts)

def build_undo_command(src_vpn, ip, mask, dest_vpn, nexthop, version=4):
    """
    构建对应的 undo 命令，不包含 preference 和 description。
    """
    parts = []
    if version == 6:
        parts.append("undo ipv6 route-static")
    else:
        parts.append("undo ip route-static")
    if src_vpn:
        parts.append(f"vpn-instance {src_vpn}")
    parts.append(ip)
    parts.append(mask)

    if dest_vpn:
        parts.append(f"vpn-instance {dest_vpn}")
    if nexthop:
        parts.append(nexthop)

    return " ".join(parts)

def generate_commands(row, row_num):
    """
    根据一行数据生成零条或多条静态路由命令及其对应的 undo 命令。
    支持目的地址和下一跳字段包含多个值（用换行符 \n 分隔），
    自动生成笛卡尔积组合。
    返回 (命令列表, undo命令列表)
    """
    src_vpn = get_clean_str(row, '源VPN实例')
    dest_raw = get_clean_str(row, '目标地址及掩码')
    nexthop_raw = get_clean_str(row, '下一跳')
    dest_vpn = get_clean_str(row, '目标vpn实例')
    priority_raw = get_clean_str(row, '优先级')
    desc = get_clean_str(row, '描述')

    # 按换行符拆分并去除空字符串
    dest_list = [d.strip() for d in dest_raw.split('\n') if d.strip()] if dest_raw else []
    nexthop_list = [n.strip() for n in nexthop_raw.split('\n') if n.strip()] if nexthop_raw else []

    # 检查必要条件
    if not dest_list:
        # print(f"警告: 第 {row_num} 行目的地址为空，跳过")
        return [], []
    if not nexthop_list and not dest_vpn:
        # print(f"警告: 第 {row_num} 行既无下一跳又无目标VPN，跳过")
        return [], []

    # 处理优先级
    priority = None
    if priority_raw:
        try:
            priority = str(int(float(priority_raw)))  # 去除小数点
        except ValueError:
            print(f"警告: 第 {row_num} 行优先级 '{priority_raw}' 不是有效数字，忽略该优先级")

    commands = []
    undo_commands = []
    # 对每个目的地址
    for dest in dest_list:
        try:
            ip, mask, version = parse_dest(dest)
        except Exception as e:
            print(f"警告: 第 {row_num} 行目的地址 '{dest}' 解析失败: {e}，跳过该地址")
            continue

        if nexthop_list:
            for nh in nexthop_list:
                cmd = build_command(src_vpn, ip, mask, dest_vpn, nh, priority, desc, version)
                commands.append(cmd)
                undo_cmd = build_undo_command(src_vpn, ip, mask, dest_vpn, nh, version)
                undo_commands.append(undo_cmd)
        else:
            # 没有下一跳（此时必须有目标VPN）
            cmd = build_command(src_vpn, ip, mask, dest_vpn, None, priority, desc, version)
            commands.append(cmd)
            undo_cmd = build_undo_command(src_vpn, ip, mask, dest_vpn, None, version)
            undo_commands.append(undo_cmd)

    return commands, undo_commands


def main(excel_path, sheet_name, output_dir, rollback_dir):
    """主处理函数"""
    print("="*60)
    print(f"开始处理Sheet: {sheet_name}")
    if not os.path.exists(excel_path):
        print(f"错误: Excel文件不存在: {excel_path}")
        return

    try:
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=0, skiprows=[1])
    except Exception as e:
        print(f"读取Excel失败: {e}")
        return

    df = df.dropna(how='all')
    if df.empty:
        print("Excel为空，无数据处理。")
        return

    required_cols = ['设备名称', '源VPN实例', '目标地址及掩码', '下一跳', '目标vpn实例']
    for col in required_cols:
        if col not in df.columns:
            print(f"错误: Excel缺少必需列 '{col}'，请检查表头。")
            return

    os.makedirs(output_dir, exist_ok=True)
    # 创建回退脚本目录
    
    os.makedirs(rollback_dir, exist_ok=True)
    success_count = 0
    rollback_count = 0
    
    grouped = df.groupby('设备名称')
    for device, group in grouped:
        if pd.isna(device) or not str(device).strip():
            print("警告: 存在设备名称为空的行，跳过。")
            continue

        all_commands = []
        all_undo_commands = []
        for idx, row in group.iterrows():
            excel_row = idx + 3
            cmds, undos = generate_commands(row, excel_row)
            all_commands.extend(cmds)
            all_undo_commands.extend(undos)

        if not all_commands:
            print(f"设备 {device} 没有生成任何命令，跳过。")
            continue

        # ----- 写入配置脚本 -----
        config_file = os.path.join(output_dir, f"{device}.txt")
        header = f"# 设备 {device} 共生成 {len(all_commands)} 条静态路由 \n\n#"
        content = "\n".join([header] + all_commands + ["#"])
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"已生成变更脚本: {config_file} (共 {len(all_commands)} 条路由)")
        success_count += 1
        # ----- 写入回退脚本 -----
        rollback_file = os.path.join(rollback_dir, f"回退脚本_{device}.txt")
        rb_header = f"# 设备 {device} 回退脚本（共 {len(all_undo_commands)} 条 undo 命令）\n\n#"
        rb_content = "\n".join([rb_header] + all_undo_commands + ["#"])
        with open(rollback_file, 'w', encoding='utf-8') as f:
            f.write(rb_content)
        print(f"已生成回退脚本: {rollback_file} (共 {len(all_undo_commands)} 条 undo 命令)")
        rollback_count += 1
        
    print(f"\n共生成 {success_count} 个变更脚本，共 {rollback_count} 个回退脚本")
    print("="*60)



if __name__ == '__main__':
    main(EXCEL_FILE, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR)
