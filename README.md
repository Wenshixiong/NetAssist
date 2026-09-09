<div align="center">

# NetAssist 网络运维工具

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Flask](https://img.shields.io/badge/Flask-3.1.2-green)
![License](https://img.shields.io/badge/License-Apache%202.0-orange)
![Version](https://img.shields.io/badge/Version-v1.5.0-brightgreen)

**面向网络工程师的本地运维工具箱：设备资产统计可视化、LLDP 自动拓扑、多场景批量脚本生成、文本对比。**

[项目地址](https://github.com/Wenshixiong/NetAssist) · [QQ 交流群：1098907087](https://qm.qq.com/q/1098907087) · 反馈邮箱：1205244490@qq.com

</div>

---

## 功能特性

### 1. 信息图表
基于设备维护清单 Excel，自动统计并可视化：
- **维保状态**：无维保 / 已过保 / 即将过保（半年内）/ 未过保，支持一键导出明细 Excel
- **EOS 状态**：服务停止 / 即将停止（2 年内）/ 服务中 / 无 EOS 信息，支持导出明细
- **设备分布**：按数据中心、业务分区、厂商、设备型号多维度统计数量与占比
- **交互筛选**：支持按型号、业务分区联动过滤，图表数据秒级刷新
- 自动排除红色底色标记的下架设备及板卡型号（CE- / CEL / CR 前缀）

### 2. 网络拓扑
基于 LLDP 采集的设备互联数据，使用 Cytoscape.js 渲染：
- **网络总拓扑**：展示全局架构，支持节点拖拽、缩放、悬停查看设备详情（型号 / IP / 序列号 / MAC / 厂商 / 分区）
- **网络分区拓扑**：按业务分区独立展示，自动筛选该分区内的设备与链路
- **坐标持久化**：拖拽后的节点坐标自动回写至 Excel「设备分区坐标表」，下次打开恢复布局
- 支持拓扑图导出为图片

### 3. 批量脚本生成
插件式架构，根据 Excel 数据源批量生成**变更脚本 + 回退脚本**，已内置 5 种场景：

| 场景模块 | 说明 |
|---|---|
| CE 基线 & 二层场景 | 交换机基础配置 + 二层业务，支持 MLAG 模板 |
| CE 三层场景 | 交换机三层接口 / 路由配置 |
| CE 静态路由 | 静态路由批量下发 |
| FW 虚墙场景 | 防火墙虚墙（vsys）配置 |
| L3GW 自定义云专线 | 自定义云专线批量生成 |

- 支持模板文件、数据源 Excel、设备名称映射表、自定义云专线文件的上传 / 下载 / 预览 / 删除
- 生成结果按目录组织，支持单文件下载或全部打包 ZIP 下载

### 4. 文本排序对比
- 对两段文本分别排序后进行差异对比（基于 diff.js）
- 快速定位配置文件、命令输出之间的差异

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3 · Flask 3.1 · waitress（生产 WSGI） |
| GUI 启动器 | tkinter · pystray（系统托盘） |
| 数据处理 | pandas · openpyxl · python-dateutil |
| 系统监控 | psutil |
| 前端 | Tailwind CSS · ECharts · Cytoscape.js · Font Awesome |
| 打包 | PyInstaller（兼容 `--add-data` 资源打包） |

---

## 快速开始

### 环境要求
- Python 3.8 及以上
- Windows / macOS / Linux（GUI 启动器与托盘在 Windows 体验最佳）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动方式

**方式一：GUI 启动器（推荐）**

```bash
python launch_v1.5.0.py
```

启动后弹出图形化管理器，可配置端口、选择缓存策略、查看运行日志，并通过系统托盘最小化。点击「启动服务」后访问 `http://127.0.0.1:5001`。

**方式二：直接启动 Web 服务**

```bash
python NetAssist_v1.5.0.py
```

服务默认监听 `0.0.0.0:5001`，浏览器访问 `http://127.0.0.1:5001`。

### 缓存策略

启动器提供三种缓存策略（通过环境变量控制）：

| 策略 | 环境变量 | 说明 |
|---|---|---|
| 全量加载（缓存） | `NETASSIST_PRELOAD=true` `NETASSIST_USE_CACHE=true` | 启动时预加载所有统计数据，图表秒开（默认） |
| 调试模式（无缓存） | `NETASSIST_PRELOAD=false` `NETASSIST_USE_CACHE=false` | 每次请求实时计算，数据始终最新，同时开启 DEBUG 日志 |

也可通过 `/refresh_cache` 接口按需刷新指定缓存键。

---

## 目录结构

```
NetAssist/
├── NetAssist_v1.5.0.py      # Flask 主应用（路由、统计、拓扑、脚本生成调度）
├── launch_v1.5.0.py         # tkinter GUI 启动器 + 系统托盘
├── version.py               # 版本元数据（唯一版本来源）
├── bump_version.py          # 版本递增工具（patch/minor/major/--set）
├── requirements.txt         # 依赖清单
├── LICENSE                  # Apache 2.0
├── html/                    # Jinja2 模板
│   ├── base.html            # 布局骨架（侧边导航）
│   ├── index.html           # 首页（功能卡片）
│   ├── info_chart.html      # 信息图表
│   ├── about.html           # 关于
│   ├── topology/            # 拓扑页面（总拓扑 / 分区拓扑）
│   └── work/                # 工作台页面（文件管理 / 场景生成 / 文本对比）
├── static/                  # 静态资源
│   ├── js/                  # ECharts / Cytoscape / diff / html-to-image
│   ├── css/                 # Tailwind 编译产物
│   ├── fontawesome-free/    # 图标字体
│   └── icons/               # 应用图标与设备类型图标
├── imported_mods/           # 插件式脚本生成模块（动态加载）
│   ├── py_CE脚本批量生成v1.2_基线&二层场景.py
│   ├── py_CE脚本批量生成v1.9_三层场景.py
│   ├── py_CE静态路由批量生成v1.3.py
│   ├── py_FW脚本批量生成v1.9_虚墙场景.py
│   └── py_L3GW自定义云专线批量生成v1.4.py
├── asset_info/              # 资产数据（设备清单 / LLDP 互联表 / 名称映射表）
├── data_uploads/            # 脚本生成数据源 Excel（可上传）
│   └── custom_line_uploads/ # 自定义云专线文件
├── templates_uploads/       # 脚本模板文件（可上传）
└── generated_scripts/       # 脚本生成输出目录（运行时自动创建）
```

---

## 数据文件说明

应用启动时会校验 `asset_info/` 目录下的两个核心 Excel，缺失则拒绝启动。可通过 `asset_info/设备清单及拓扑映射表_示例.txt` 指定实际文件名：

```ini
EXCEL_FILENAME=设备维护清单.xlsx
LLDP_FILENAME=设备信息及互联表.xlsx
```

### 设备维护清单.xlsx
| Sheet | 用途 | 关键列 |
|---|---|---|
| 设备清单 | 设备资产主表 | 设备型号、数据中心、业务分区、维保开始/结束、序列号、管理地址 |
| 设备EOS信息 | 型号 → EOS 时间映射 | 设备型号、设备EOS时间 |
| 其他厂商设备数量 | 厂商设备数量汇总 | 厂商、数量 |

> 红色底色行自动视为下架设备并排除；`CE-` / `CEL` / `CR` 前缀视为板卡并排除。

### 设备信息及互联表.xlsx（LLDP）
| Sheet | 用途 | 关键列 |
|---|---|---|
| 设备基础信息表 | 设备静态信息 | 设备名称、所属分区、所属数据中心、序列号SN、MAC地址、设备型号、管理地址、是否在总拓扑体现 |
| 设备分区坐标表 | 拓扑节点坐标 | 设备名称、当前分区、topology_x、topology_y |
| 设备分区互联表 | 设备链路关系 | 所属分区、本端设备名称、本端设备接口、远端设备名称、远端设备接口 |

---

## 开发说明

### 版本管理
版本号唯一来源为 `version.py`，使用 `bump_version.py` 统一递增并自动重命名主程序与启动器文件：

```bash
python bump_version.py              # 1.5.0 -> 1.5.1（patch）
python bump_version.py --minor      # 1.5.1 -> 1.6.0
python bump_version.py --major      # 1.6.0 -> 2.0.0
python bump_version.py --set 2.1.0  # 显式设置
```

### 新增脚本生成场景
1. 在 `imported_mods/` 中新增模块，暴露 `main(EXCEL_NAME, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, ...)` 入口
2. 在 `NetAssist_v1.5.0.py` 中通过 `load_module_from_path()` 动态加载
3. 在 `/generate_scripts` 路由中按数据源文件名关键字分发到对应模块

### 环境变量
| 变量 | 默认 | 说明 |
|---|---|---|
| `FLASK_SECRET_KEY` | `dev_secret_key_should_be_changed` | Flask 会话密钥，生产环境务必修改 |
| `NETASSIST_PRELOAD` | `true` | 启动时是否预加载统计缓存 |
| `NETASSIST_USE_CACHE` | `true` | 请求是否使用缓存 |
| `NETASSIST_DEBUG` | `false` | 是否输出 DEBUG 级日志 |

---

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源，Copyright © 2026 Wenshixiong/NetAssist。
