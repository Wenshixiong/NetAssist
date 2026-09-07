import sys
import re
import os
import logging
from openpyxl import load_workbook


# ========== 用户可配置区域 ==========
EXCEL_FILE = "excel_L3GW自定义云专线批量生成v1.4.xlsx"
SHEET_NAME = "自定义云专线静态路由"
OUTPUT_DIR = "output"
ROLLBACK_DIR = os.path.join(OUTPUT_DIR, "回退脚本")
CUSTOM_LINE_DIR = "custom_line_uploads"
CUSTOM_LINE = ""


# 列名映射（可自由修改）
column_mapping = {
    "vpc_subnet": "VPC子网",
    "custom_inst": "自定义实例",
    "remote_subnet": "远端子网",
    "vpc_name": "VPC名称"
}

# 描述模板（空字符串表示不生成description）
# 可用变量：{custom_inst}, {vpc_name}, {l3gw_inst}, {vpc_ip}, {vpc_mask}, {remote_ip}, {remote_mask}
# 若C列不参与描述，可设为空字符串
# description_templates = {"step7": "", "step6": ""}
# 若C列参与描述，可取消注释以下代码
description_templates = {
    "step7": "{custom_inst}-to-{vpc_name}",
    "step6": "l3gw-to-{custom_inst}"
}

# ---- 多任务配置 ----
# 方式1：统一下发脚本（所有Sheet共用）
# downlink_script = "下发脚本_样例_ipv6.txt"
# 方式2：根据Sheet名称动态确定下发脚本（例如 "下发脚本_{sheet_name}.txt"）
def get_script_path(sheet_name):
    # 示例：使用固定脚本，或根据sheet名构造
    # return "下发脚本_样例_ipv6.txt"  # 默认都使用同一个
    return f"下发脚本_{sheet_name}.txt"  # 可取消注释以使用独立脚本


# ==================================


# 全局统计路由总数（所有Sheet累计）
total_route_count = 0

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ========== IPv6 支持函数（保持不变） ==========
def is_ipv6(subnet_str):
    return ':' in str(subnet_str)

def parse_ipv6_cidr(subnet_str):
    clean = re.sub(r'\s+', '', str(subnet_str))
    if '/' not in clean:
        raise ValueError(f"IPv6 子网缺少 '/'：{clean}")
    ip, prefix = clean.split('/', 1)
    if not ip or not prefix:
        raise ValueError(f"IPv6 子网 IP 或前缀为空：{clean}")
    try:
        prefix_len = int(prefix)
        if not 0 <= prefix_len <= 128:
            raise ValueError(f"IPv6 前缀 {prefix_len} 超出 0-128 范围")
    except ValueError:
        raise ValueError(f"IPv6 前缀不是有效数字：{prefix}")
    return ip, str(prefix_len)

def cidr_to_subnet(cidr_str):
    try:
        clean_cidr = re.sub(r'\s+', '', str(cidr_str))
        cidr = int(clean_cidr)
        if not 0 <= cidr <= 32:
            raise ValueError(f"CIDR掩码{cidr}超出0-32合法范围")
        subnet_segments = []
        remaining_bits = cidr
        for _ in range(4):
            if remaining_bits >= 8:
                subnet_segments.append(255)
                remaining_bits -= 8
            elif remaining_bits > 0:
                subnet_segments.append(256 - (1 << (8 - remaining_bits)))
                remaining_bits = 0
            else:
                subnet_segments.append(0)
        return '.'.join(map(str, subnet_segments))
    except ValueError as e:
        logging.error(f"CIDR掩码转换失败: {e}（原始输入：{cidr_str}）")
        raise

def parse_downlink_script(script_path):
    """
    解析单个下发脚本，返回路由映射 {(目标IP, 掩码): (l3gw实例, vpc实例)}
    """
    route_mapping = {}
    route_pattern = re.compile(
        r'(?:ip|ipv6) route-static vpn-instance (\S+) (\S+) (\S+) vpn-instance (\S+) description BY_CONTROLLER'
    )
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            valid_lines = [line.strip() for line in f if line.strip()]
        for line_num, line in enumerate(valid_lines, 1):
            match_result = route_pattern.match(line)
            if not match_result:
                logging.debug(f"下发脚本第{line_num}行格式不匹配（跳过）: {line}")
                continue
            inst_a, route_ip, route_mask, inst_b = match_result.groups()
            l3gw_instance = inst_a if inst_a.startswith('l3gw_') else inst_b if inst_b.startswith('l3gw_') else None
            vpc_instance = inst_a if inst_a.startswith('vpc') else inst_b if inst_b.startswith('vpc') else None
            if not l3gw_instance or not vpc_instance:
                logging.debug(f"下发脚本第{line_num}行未找到有效实例（跳过）: {line}")
                continue
            route_key = (route_ip, route_mask)
            route_mapping[route_key] = (l3gw_instance, vpc_instance)
            logging.debug(f"解析成功 - IP:{route_ip} | 掩码:{route_mask} | l3gw:{l3gw_instance} | vpc:{vpc_instance}")
        logging.debug(f"下发脚本解析完成，共获取 {len(route_mapping)} 条有效路由映射")
        return route_mapping
    except Exception as e:
        raise

def split_subnets(subnet_str):
    if not subnet_str or str(subnet_str).strip() == '':
        return []
    unified_str = str(subnet_str).replace('<br/>', '\n')
    subnets = [
        re.sub(r'\s+', '', subnet)
        for subnet in unified_str.split('\n')
        if subnet.strip()
    ]
    return subnets

def process_sheet(ws, sheet_name, route_mapping, col_mapping, desc_templates=None):
    """
    处理单个 Sheet，返回该 Sheet 生成的路由列表、回退路由列表和该 Sheet 的路由计数。
    """
    global total_route_count
    sheet_route_count = 0
    generated_routes = []
    undo_routes = []          # 【新增】存储 undo 命令
    step6_keys = set()
    step7_keys = set()

    # 描述模板
    if desc_templates is None:
        desc_templates = {"step7": "{custom_inst}-to-{vpc_name}", "step6": "l3gw-to-{custom_inst}"}
    step7_template = desc_templates.get("step7", "{custom_inst}-to-{vpc_name}")
    step6_template = desc_templates.get("step6", "l3gw-to-{custom_inst}")

    # 列名映射
    col_vpc_subnet_name = col_mapping.get("vpc_subnet")
    col_custom_inst_name = col_mapping.get("custom_inst")
    col_remote_subnet_name = col_mapping.get("remote_subnet")
    col_vpc_name_name = col_mapping.get("vpc_name")

    if not all([col_vpc_subnet_name, col_custom_inst_name, col_remote_subnet_name]):
        raise ValueError("列名映射缺少必要项：'vpc_subnet', 'custom_inst', 'remote_subnet'")

    # 读取表头
    header_row = ws[1]
    header = [str(cell.value).strip() if cell.value else '' for cell in header_row]

    try:
        col_vpc_subnet = header.index(col_vpc_subnet_name)
        col_custom_inst = header.index(col_custom_inst_name)
        col_remote_subnet = header.index(col_remote_subnet_name)
    except ValueError as e:
        logging.error(f"Sheet {sheet_name} 中找不到必要列: {e}")
        return [], [], 0

    col_vpc_name = header.index(col_vpc_name_name) if col_vpc_name_name and col_vpc_name_name in header else None

    prev_vals = {}
    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        row_data = list(row) if row else []

        def get_val(col_idx):
            if col_idx is None:
                return None
            val = row_data[col_idx] if col_idx < len(row_data) else None
            if val is None or str(val).strip() == '':
                return prev_vals.get(col_idx, None)
            return str(val).strip()

        vpc_subnet_str = get_val(col_vpc_subnet)
        custom_inst = get_val(col_custom_inst)
        remote_subnet_str = get_val(col_remote_subnet)
        vpc_name = get_val(col_vpc_name) if col_vpc_name is not None else None

        if not vpc_subnet_str or not custom_inst:
            prev_vals[col_vpc_subnet] = vpc_subnet_str
            prev_vals[col_custom_inst] = custom_inst
            prev_vals[col_remote_subnet] = remote_subnet_str
            if col_vpc_name is not None:
                prev_vals[col_vpc_name] = vpc_name
            continue

        vpc_subnets = split_subnets(vpc_subnet_str)
        remote_subnets = split_subnets(remote_subnet_str)
        if not vpc_subnets:
            continue

        for vpc_subnet in vpc_subnets:
            # 解析VPC子网
            vpc_clean = re.sub(r'\s+', '', vpc_subnet)
            if '/' not in vpc_clean:
                logging.error(f"VPC子网 {vpc_clean} 格式错误，跳过")
                continue
            if is_ipv6(vpc_clean):
                try:
                    vpc_ip, vpc_mask = parse_ipv6_cidr(vpc_clean)
                    cmd_prefix_vpc = "ipv6 route-static"
                except ValueError as e:
                    logging.error(f"VPC子网 {vpc_clean} IPv6解析失败: {e}，跳过")
                    continue
            else:
                vpc_ip, vpc_cidr = vpc_clean.split('/', 1)
                try:
                    vpc_mask = cidr_to_subnet(vpc_cidr)
                    cmd_prefix_vpc = "ip route-static"
                except ValueError:
                    logging.error(f"VPC子网 {vpc_clean} CIDR解析失败，跳过")
                    continue

            # 查找l3gw
            vpc_route_key = (vpc_ip, vpc_mask)
            if vpc_route_key not in route_mapping:
                logging.error(f"VPC子网 {vpc_clean} 未在下发脚本中找到匹配路由，跳过")
                continue
            l3gw_inst, _ = route_mapping[vpc_route_key]

            # 步骤7（去重）
            step7_key = (custom_inst, vpc_ip, vpc_mask, l3gw_inst)
            if step7_key not in step7_keys:
                step7_keys.add(step7_key)
                # 正向路由
                if step7_template:
                    desc_vpc = step7_template.format(
                        custom_inst=custom_inst,
                        vpc_name=vpc_name if vpc_name else 'vpc',
                        l3gw_inst=l3gw_inst,
                        vpc_ip=vpc_ip,
                        vpc_mask=vpc_mask
                    )
                    route7 = f"{cmd_prefix_vpc} vpn-instance {custom_inst} {vpc_ip} {vpc_mask} vpn-instance {l3gw_inst} description {desc_vpc}"
                else:
                    route7 = f"{cmd_prefix_vpc} vpn-instance {custom_inst} {vpc_ip} {vpc_mask} vpn-instance {l3gw_inst}"
                generated_routes.append(route7)
                # 【新增】回退路由（不带 description）
                undo_route7 = f"undo {cmd_prefix_vpc} vpn-instance {custom_inst} {vpc_ip} {vpc_mask} vpn-instance {l3gw_inst}"
                undo_routes.append(undo_route7)

                sheet_route_count += 1
                total_route_count += 1

            # 步骤6（去重）
            if remote_subnets:
                for remote_subnet in remote_subnets:
                    remote_clean = re.sub(r'\s+', '', remote_subnet)
                    if '/' not in remote_clean:
                        logging.error(f"远端子网 {remote_clean} 格式错误，跳过")
                        continue
                    if is_ipv6(remote_clean):
                        try:
                            remote_ip, remote_mask = parse_ipv6_cidr(remote_clean)
                            cmd_prefix_remote = "ipv6 route-static"
                        except ValueError as e:
                            logging.error(f"远端子网 {remote_clean} IPv6解析失败: {e}，跳过")
                            continue
                    else:
                        remote_ip, remote_cidr = remote_clean.split('/', 1)
                        try:
                            remote_mask = cidr_to_subnet(remote_cidr)
                            cmd_prefix_remote = "ip route-static"
                        except ValueError:
                            logging.error(f"远端子网 {remote_clean} CIDR解析失败，跳过")
                            continue

                    step6_key = (l3gw_inst, remote_ip, remote_mask)
                    if step6_key in step6_keys:
                        continue
                    step6_keys.add(step6_key)

                    # 正向路由
                    if step6_template:
                        desc_l3gw = step6_template.format(
                            custom_inst=custom_inst,
                            l3gw_inst=l3gw_inst,
                            vpc_name=vpc_name if vpc_name else 'vpc',
                            remote_ip=remote_ip,
                            remote_mask=remote_mask
                        )
                        route6 = f"{cmd_prefix_remote} vpn-instance {l3gw_inst} {remote_ip} {remote_mask} vpn-instance {custom_inst} description {desc_l3gw}"
                    else:
                        route6 = f"{cmd_prefix_remote} vpn-instance {l3gw_inst} {remote_ip} {remote_mask} vpn-instance {custom_inst}"
                    generated_routes.append(route6)
                    # 【新增】回退路由（不带 description）
                    undo_route6 = f"undo {cmd_prefix_remote} vpn-instance {l3gw_inst} {remote_ip} {remote_mask} vpn-instance {custom_inst}"
                    undo_routes.append(undo_route6)

                    sheet_route_count += 1
                    total_route_count += 1

        # 更新缓存
        prev_vals[col_vpc_subnet] = vpc_subnet_str
        prev_vals[col_custom_inst] = custom_inst
        prev_vals[col_remote_subnet] = remote_subnet_str
        if col_vpc_name is not None:
            prev_vals[col_vpc_name] = vpc_name

    return generated_routes, undo_routes, sheet_route_count

def main(excel_path, sheet_name, output_dir, rollback_dir, custom_line_dir, custom_line):

    try:
        print("=" * 60)
        wb = load_workbook(excel_path)
        # 获取所有Sheet（排除“须知”）
        # sheet_names = [name for name in wb.sheetnames if name != '须知']
        # if not sheet_names:
        #     logging.error("Excel中无可处理的Sheet（不含“须知”）")
        #     sys.exit(1)

        # for sheet_name in sheet_names:
        print(f"开始处理Sheet: {sheet_name}")
        # 获取该Sheet对应的下发脚本路径
        
        if custom_line:
            script_path = os.path.join(custom_line_dir, custom_line)
        else:
            script_path = get_script_path(sheet_name)
        print(f"使用已下发的脚本: {script_path}")

        # 解析该下发脚本
        try:
            route_mapping = parse_downlink_script(script_path)
        except Exception as e:
            logging.error(f"Sheet '{sheet_name}' 下发脚本解析失败: {e}")
            return
            # continue

        if not route_mapping:
            logging.error(f"Sheet {sheet_name} 对应的下发脚本解析失败或为空")
            # continue
            return

        # 获取Sheet对象
        ws = wb[sheet_name]
        # 【修改】接收三个返回值
        routes, undo_routes, count = process_sheet(ws, sheet_name, route_mapping, column_mapping, description_templates)

        if count == 0:
            logging.warning(f"Sheet {sheet_name} 未生成任何路由，跳过写入")
            return
            # continue
        os.makedirs(rollback_dir, exist_ok=True)
        # 输出文件名模板（使用 {sheet_name} 占位符）
        output_name_template = f"云专线变更脚本_{sheet_name}.txt"
        # 或者自定义前缀后缀：output_name_template = "prefix_{sheet_name}_suffix.txt"
        # 【新增】回退脚本文件名模板
        undo_output_name_template = f"云专线回退脚本_{sheet_name}.txt"

        # ---- 生成正向脚本 ----
        output_path = os.path.join(output_dir, output_name_template.format(sheet_name=sheet_name))
        # 在脚本开头添加该Sheet的路由总数注释
        content = f"# Sheet: {sheet_name}，共生成 {count} 条路由\n\n#\n" + "\n".join(routes) + "\n#"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"生成变更脚本: {output_path}")

        
        # ---- 【新增】生成回退脚本 ----
        undo_output_path = os.path.join(rollback_dir, undo_output_name_template.format(sheet_name=sheet_name))
        undo_content = f"# Sheet: {sheet_name}，回退脚本，共 {count} 条 undo 命令\n\n#\n" + "\n".join(undo_routes) + "\n#"
        with open(undo_output_path, 'w', encoding='utf-8') as f:
            f.write(undo_content)
        print(f"生成回退脚本: {undo_output_path}")

        print(f"共生成 {count} 条路由，共生成 {count} 条 undo 命令")
        print("=" * 60)
        wb.close()

    except Exception as e:
        logging.error(f"脚本执行失败: {e}")
        raise

if __name__ == "__main__":
    main(EXCEL_FILE, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, CUSTOM_LINE_DIR, CUSTOM_LINE)
