# NetAssist v1.5.2 发布说明

## 许可证

本项目基于 **Apache License 2.0** 开源协议发布。

> Copyright 2026 Wenshixiong/NetAssist
>
> Licensed under the Apache License, Version 2.0 (the "License");
> you may not use this file except in compliance with the License.
> You may obtain a copy of the License at
>
>     http://www.apache.org/licenses/LICENSE-2.0
>
> Unless required by applicable law or agreed to in writing, software
> distributed under the License is distributed on an "AS IS" BASIS,
> WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
> See the License for the specific language governing permissions and
> limitations under the License.

完整许可证文本见项目根目录 [LICENSE](LICENSE) 文件，或在程序「关于」页面中查看。

---

## 版本信息

| 项 | 内容 |
|---|---|
| 版本号 | v1.5.2 |
| 发布日期 | 2026-09-09 |
| 开发语言 | Python 3 |
| 开发框架 | Flask + Tailwind CSS |
| 项目地址 | https://github.com/Wenshixiong/NetAssist |

---

## 功能概览

### 信息图表
- 设备维保状态统计（无维保 / 已过保 / 即将过保 / 未过保），支持导出明细 Excel
- 设备 EOS 状态统计（服务停止 / 即将停止 / 服务中 / 无 EOS 信息），支持导出明细 Excel
- 按数据中心、业务分区、厂商、设备型号多维度统计设备数量与占比
- 支持按型号、业务分区联动筛选，自动排除红色底色标记的下架设备及板卡型号

### 网络拓扑
- 基于 LLDP 数据自动生成网络总拓扑和分区拓扑（Cytoscape.js）
- 支持节点拖拽、缩放、悬停查看设备详情（型号 / IP / 序列号 / MAC / 厂商 / 分区）
- 拖拽后的节点坐标自动回写至 Excel，下次打开恢复布局
- 支持拓扑图导出为图片

### 批量脚本生成
- 插件式架构，根据 Excel 数据源批量生成变更脚本 + 回退脚本
- 内置 5 种场景：CE 基线 & 二层、CE 三层、CE 静态路由、FW 虚墙、L3GW 自定义云专线
- 支持模板文件、数据源、设备名称映射表、自定义云专线文件的上传 / 下载 / 预览 / 删除
- 生成结果支持单文件下载或全部打包 ZIP 下载

### 文本排序对比
- 对两段文本分别排序后进行差异对比，快速定位配置文件、命令输出之间的差异

---

## 运行方式

### 源码运行
```bash
pip install -r requirements.txt
python launch_v1.5.2.py
```
服务默认监听 `http://127.0.0.1:5001`。

### 打包为 exe
```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name "NetAssist_v1.5.2" --icon="static/icons/NetAssist_64.ico" ^
    --add-data "asset_info;asset_info" ^
    --add-data "html;html" ^
    --add-data "templates_uploads;templates_uploads" ^
    --add-data "data_uploads;data_uploads" ^
    --add-data "imported_mods;imported_mods" ^
    --add-data "static/css;static/css" ^
    --add-data "static/icons;static/icons" ^
    --add-data "static/js;static/js" ^
    --add-data "static/fontawesome-free;static/fontawesome-free" ^
    launch_v1.5.2.py
```

---

## 联系方式

- 开发作者：Wenshixiong
- QQ 交流群：1098907087
- 反馈邮箱：1205244490@qq.com
