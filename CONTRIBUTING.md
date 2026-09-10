# 贡献指南

感谢你对 NetAssist 的关注！欢迎提交 Issue 和 Pull Request。

## 开发环境搭建

```bash
# 1. 克隆仓库
git clone https://github.com/Wenshixiong/NetAssist.git
cd NetAssist

# 2. 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # macOS/Linux

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动开发服务
python launch_v1.5.3.py
```

访问 `http://127.0.0.1:5001` 即可。

## 样式开发

项目使用 Tailwind CSS CLI 编译样式：

```bash
cd static/TailwindCSS_CLI
npm install
npx tailwindcss -i ./src/input.css -o ../css/output.css --watch
```

修改 HTML 中的 Tailwind 类名后，`--watch` 会自动重新编译 `static/css/output.css`。

## 提交 PR 流程

1. Fork 本仓库
2. 从 `main` 分支创建特性分支：`git checkout -b feature/your-feature`
3. 提交代码：`git commit -m "feat: 描述你的改动"`
4. 推送到你的 Fork：`git push origin feature/your-feature`
5. 在 GitHub 上发起 Pull Request，目标分支为 `main`

> 注意：`main` 分支已开启分支保护，所有改动必须通过 PR 合入，至少 1 人审批。

## 代码规范

- Python 代码遵循 PEP 8，缩进 4 空格
- 模板文件放在 `html/` 目录，静态资源放在 `static/`
- 新增脚本生成场景时，在 `imported_mods/` 中添加模块，并在主程序中注册
- 提交前请确保程序能正常启动，核心功能无报错

## 提交信息格式

建议使用以下前缀：

| 前缀 | 说明 |
|---|---|
| `feat:` | 新功能 |
| `fix:` | 修复 bug |
| `docs:` | 文档更新 |
| `style:` | 样式/格式调整（不影响逻辑） |
| `refactor:` | 重构 |
| `perf:` | 性能优化 |
| `chore:` | 构建/工具/依赖变动 |

## 报告问题

提交 Issue 时请尽量包含：
- 问题描述与复现步骤
- 操作系统、Python 版本
- 报错截图或日志
- 期望行为

安全漏洞请**不要**公开提交 Issue，通过邮箱 `1205244490@qq.com` 私下联系作者，详见 [SECURITY.md](SECURITY.md)。
