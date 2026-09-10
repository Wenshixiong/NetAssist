# -*- coding: utf-8 -*-
"""
NetAssist 服务图形化管理器 - 简洁布局版
增加缓存策略选择功能
"""
from waitress import serve
import sys
import os
import threading
import queue
import multiprocessing
import socket
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from PIL import Image, ImageDraw
import pystray
import ctypes
import re
import webbrowser
from version import APP_NAME, version_text

# ---------- 资源路径 ----------
def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)

# ---------- 全局变量 ----------
flask_process = None
log_queue = multiprocessing.Queue()
root_window = None
tray_icon = None
is_window_visible = True
system_icon = resource_path("static/icons/NetAssist_64.png")
windows_icon = resource_path("static/icons/NetAssist_64.ico")
title_name = f"{APP_NAME}{version_text()}"
DEFAULT_PORT = 5001
# ---------- 端口检测 ----------
def is_port_in_use(port, host='127.0.0.1'):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False, None
        except OSError as e:
            return True, str(e)

# ---------- 运行 NetAssist ----------
def run_netassist(q, port, env=None):
    # 应用环境变量（如果提供）
    if env is not None:
        os.environ.update(env)
    # os.environ['NO_COLOR'] = '1'   # 告诉 Werkzeug 不要输出颜色
    class QueueWriter:
        def __init__(self, queue):
            self.queue = queue
            self.ansi_escape = re.compile(r'\x1b\[[0-9;]*m')  # 匹配所有 ANSI 颜色码
        def write(self, msg):
            if msg is None:
                return
            # 如果是字节，解码为字符串（处理可能的编码错误）
            if isinstance(msg, bytes):
                try:
                    msg = msg.decode('utf-8')
                except UnicodeDecodeError:
                    msg = msg.decode('latin-1')   # 回退编码
            # 剔除所有 ANSI 颜色转义序列
            clean_msg = self.ansi_escape.sub('', msg)
            if clean_msg.strip():
                self.queue.put(clean_msg.strip())
        def flush(self):
            pass
    sys.stdout = QueueWriter(q)
    sys.stderr = QueueWriter(q)
    try:

        # 以模块方式引入主应用（NetAssist.py 已固定文件名，不含版本号）
        # 放在函数内延迟加载：仅子进程序需要加载 Flask/pandas 等重型依赖，GUI 主窗口启动不受影响
        import NetAssist as NetAssist_app
        # 先执行缓存初始化（会输出日志到 QueueWriter）
        NetAssist_app.initialize_cache()
        # 再启动 Web 服务器
        # Waitress 生产服务器启动
        serve(NetAssist_app.app, host='0.0.0.0', port=port, threads=8)
        # Werkzeug 开发服务器启动
        # NetAssist_app.app.run(host='127.0.0.1', port=port, debug=True)
        
    except Exception as e:
        print(f"NetAssist 启动失败: {e}")

# ---------- GUI 主类 ----------
class NetAssistGUI:
    def __init__(self, master):
        self.master = master
        master.title(title_name)
        master.geometry("800x500")  # 增加高度以容纳新控件
        master.resizable(True, True)
        master.protocol("WM_DELETE_WINDOW", self.hide_window)

        # 创建日志目录
        # 确定基础目录：打包后为 exe 所在目录，开发环境为当前文件所在目录
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)   # exe 所在目录
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        self.log_filename = os.path.join(log_dir, f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self.current_port = DEFAULT_PORT

        # ---------- 1. 状态标签（顶部，居中） ----------
        self.status_label = tk.Label(master, text=f"未启动  |  端口: {self.current_port}",
                                     font=("Segoe UI", 14, "bold"), fg="gray")
        self.status_label.pack(pady=(15, 5))

        # ---------- 2. 端口设置行（居中） ----------
        port_container = tk.Frame(master)
        port_container.pack(pady=8, fill=tk.X)

        # 内部 Frame 用于居中所有控件
        port_frame = tk.Frame(port_container)
        port_frame.pack(anchor='center')

        tk.Label(port_frame, text="端口:", font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0,6))

        self.port_var = tk.StringVar(value=str(self.current_port))
        self.port_entry = tk.Entry(port_frame, textvariable=self.port_var, width=8,
                                   font=("Segoe UI", 10), relief=tk.SOLID, bd=1)
        self.port_entry.pack(side=tk.LEFT, padx=(0,10))

        self.check_port_btn = ttk.Button(port_frame, text="检测端口", command=self.check_port,
                                         width=10)
        self.check_port_btn.pack(side=tk.LEFT, padx=(0,10))

        self.port_status_label = tk.Label(port_frame, text="未测端口", fg="gray")
        self.port_status_label.pack(side=tk.LEFT)

        # ---------- 3. 缓存策略选择（新增） ----------
        cache_frame = tk.Frame(master)
        cache_frame.pack(pady=6)

        tk.Label(cache_frame, text="缓存策略:", font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0,6))

        self.cache_strategy_var = tk.StringVar(value="preload") 
        strategy_options = [
            ("全量加载(缓存)", "preload"),
            # ("首次加载+缓存（调试场景1）", "lazy"),
            ("调试模式(无缓存)", "realtime")
        ]
        for text, value in strategy_options:
            tk.Radiobutton(cache_frame, text=text, variable=self.cache_strategy_var,
                        value=value, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=5)


        # ---------- 4. 操作按钮行（居中） ----------
        btn_container = tk.Frame(master)
        btn_container.pack(pady=12)

        btn_frame = tk.Frame(btn_container)
        btn_frame.pack(anchor='center')
        self.open_web_btn = ttk.Button(btn_frame, text="打开网页", command=self.open_webpage, width=12)
        self.open_web_btn.pack(side=tk.LEFT, padx=6)

        self.start_btn = ttk.Button(btn_frame, text="启动服务", command=self.start_netassist,
                                    width=12)
        self.start_btn.pack(side=tk.LEFT, padx=6)

        self.stop_btn = ttk.Button(btn_frame, text="停止服务", command=self.stop_netassist,
                                   state=tk.DISABLED, width=12)
        self.stop_btn.pack(side=tk.LEFT, padx=6)

        self.quit_btn = ttk.Button(btn_frame, text="退出", command=self.quit_app, width=12)
        self.quit_btn.pack(side=tk.LEFT, padx=6)

        # ---------- 5. 日志区域 ----------
        log_frame = tk.LabelFrame(master, text=" 运行日志 ", font=("Segoe UI", 10, "bold"))
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(8, 18))

        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, wrap=tk.WORD,
                                                  font=("Consolas", 9), bg="#fafafa")
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.log_text.config(state='disabled')

        # ---------- 设置窗口图标 ----------
        if os.path.exists(windows_icon):
            try:
                self.master.iconbitmap(default=windows_icon)
            except:
                pass
        # 先显示窗口
        self.master.update()
        # 然后执行耗时初始化 
        self.create_tray_icon()
        self.poll_log_queue()
        self.log_message("NetAssist GUI 已启动")

    # ---------- 日志 ----------
    def log_message(self, msg, level='INFO'):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {level}: {msg}"
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, formatted + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        try:
            with open(self.log_filename, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except:
            pass

    def poll_log_queue(self):
        try:
            while True:
                msg = log_queue.get_nowait()
                self.log_message(msg, 'NETASSIST')
        except queue.Empty:
            pass
        self.master.after(100, self.poll_log_queue)

    # ---------- 端口检测 ----------
    def _update_port_status(self, port):
        """更新端口状态标签（无弹窗）"""
        in_use, _ = is_port_in_use(port)
        if in_use:
            self.port_status_label.config(text="端口被占用", fg="red")
        else:
            self.port_status_label.config(text="端口可用", fg="green")
        return in_use

    def check_port(self):
        """手动检测端口（带弹窗提示）"""
        port_str = self.port_var.get().strip()
        if not port_str.isdigit():
            self.port_status_label.config(text="端口号无效", fg="red")
            messagebox.showerror("错误", "端口号必须是数字")
            return
        port = int(port_str)
        if port < 1 or port > 65535:
            self.port_status_label.config(text="范围错误", fg="red")
            messagebox.showerror("错误", "端口范围 1-65535")
            return

        in_use = self._update_port_status(port)
        if in_use:
            messagebox.showwarning("端口冲突", f"端口 {port} 已被占用")


    # ---------- 托盘 ----------
    def _create_default_icon(self):
        image = Image.new('RGB', (64, 64), color=(70, 130, 180))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
        return image

    def _get_menu(self):
        is_running = flask_process is not None and flask_process.is_alive()
        return pystray.Menu(
            pystray.MenuItem("显示窗口", self.show_window),
            pystray.MenuItem("启动服务", self.start_netassist, enabled=not is_running),
            pystray.MenuItem("停止服务", self.stop_netassist, enabled=is_running),
            pystray.MenuItem("退出", self.quit_app),
        )

    def create_tray_icon(self):
        if os.path.exists(system_icon):
            try:
                image = Image.open(system_icon)

            except Exception as e:
                self.log_message(f"托盘图标打开失败: {e}", "ERROR")
                image = self._create_default_icon()
        else:
            self.log_message(f"托盘图标文件不存在: {system_icon}", "ERROR")
            image = self._create_default_icon()
        global tray_icon
        tray_icon = pystray.Icon("netassist_icon", image, "NetAssist 管理器", menu=self._get_menu())


    def _update_tray_menu(self):
        global tray_icon
        if tray_icon:
            tray_icon.menu = self._get_menu()
            tray_icon.update_menu()

    def show_window(self, icon=None, item=None):
        if self.master is None:
            return
        try:
            if not self.master.winfo_exists():
                return
        except:
            return
        self.master.deiconify()
        self.master.lift()
        self.master.focus_force()
        global is_window_visible
        is_window_visible = True

    def hide_window(self):
        global is_window_visible
        self.master.withdraw()
        is_window_visible = False

    def open_webpage(self):
        """用默认浏览器打开服务网页"""
        global flask_process
        # 判断服务是否运行
        if flask_process is None or not flask_process.is_alive():
            messagebox.showwarning("提示", "服务尚未启动，请先点击【启动服务】")
            return
        port = self.current_port
        url = f"http://127.0.0.1:{port}/"
        webbrowser.open(url)
        self.log_message(f"浏览器访问地址：{url}")


    # ---------- 启动/停止 ----------
    def start_netassist(self):
        global flask_process
        if flask_process and flask_process.is_alive():
            messagebox.showinfo("提示", "NetAssist 服务已在运行")
            return

        port_str = self.port_var.get().strip()
        if not port_str.isdigit():
            messagebox.showerror("错误", "端口号必须是数字")
            return
        port = int(port_str)
        if port < 1 or port > 65535:
            messagebox.showerror("错误", "端口范围 1-65535")
            return

        # 自动检测端口并更新状态标签
        in_use = self._update_port_status(port)
        if in_use:
            messagebox.showerror("端口冲突", f"端口 {port} 已被占用，请更换端口")
            return

        # 根据缓存策略设置环境变量
        strategy = self.cache_strategy_var.get()
        self.current_strategy = strategy
        env = os.environ.copy()
        if strategy == "preload":
            env['NETASSIST_PRELOAD'] = 'true'
            env['NETASSIST_USE_CACHE'] = 'true'
        elif strategy == "lazy":
            env['NETASSIST_PRELOAD'] = 'false'
            env['NETASSIST_USE_CACHE'] = 'true'
        elif strategy == "realtime":
            env['NETASSIST_PRELOAD'] = 'false'
            env['NETASSIST_USE_CACHE'] = 'false'

        # ===== 新增：传递调试日志开关 =====
        env['NETASSIST_DEBUG'] = 'true' if strategy == "realtime" else 'false'

        # 清空日志、更新界面
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')

        self.current_port = port
        self.status_label.config(text=f"启动中  |  端口: {port}", fg="orange")
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.port_entry.config(state="disabled")
        self.check_port_btn.config(state="disabled")
        self.log_message(f"正在启动 NetAssist 服务")

        try:
            flask_process = multiprocessing.Process(
                target=run_netassist,
                args=(log_queue, port, env),
                daemon=False
            )
            flask_process.start()

            def check_process():
                if flask_process and flask_process.is_alive():
                    self.status_label.config(text=f"运行中  |  端口: {port}", fg="green")
                    self.start_btn.config(state=tk.DISABLED)
                    self.stop_btn.config(state=tk.NORMAL)
                    # self.log_message(f"NetAssist 服务启动成功")
                    # self.log_message(f"访问地址：http://127.0.0.1:{port}")
                    # 新增：提示缓存策略及预加载状态
                    strategy_desc = {
                        "preload": "启动时预加载（所有数据已缓存）",
                        "lazy": "首次访问时加载（后续请求使用缓存）",
                        "realtime": "每次请求实时计算（不缓存）"
                    }
                    
                    # self.log_message(f"[策略] {strategy_desc.get(self.current_strategy, self.current_strategy)}")
                    # if self.current_strategy == "preload":
                    #     self.log_message("预加载已在服务启动时完成，所有图表数据将秒开")
                    # elif self.current_strategy == "lazy":
                    #     self.log_message("首次访问信息图表时进行数据加载，之后将使用缓存")
                    # else:
                    #     self.log_message("每次请求均实时计算，数据始终最新")
                    # 在启动成功日志后添加
                    debug_status = "开启" if self.current_strategy == "realtime" else "关闭"
                    # self.log_message(f"调试日志: {debug_status}")
                    self._update_tray_menu()
                else:
                    self.log_message("NetAssist 进程启动失败，请检查日志", "ERROR")
                    self.status_label.config(text="启动失败", fg="red")
                    self.start_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    self.port_entry.config(state="normal")
                    self.check_port_btn.config(state="normal")
                    self.poll_log_queue()
            self.master.after(1000, check_process)
        except Exception as e:
            self.log_message(f"启动异常: {e}", "ERROR")
            self.status_label.config(text="启动失败", fg="red")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.port_entry.config(state="normal")
            self.check_port_btn.config(state="normal")

    def stop_netassist(self):
        global flask_process
        if flask_process is None or not flask_process.is_alive():
            messagebox.showinfo("提示", "NetAssist 服务未运行")
            return
        self.log_message("正在停止 NetAssist 服务...")
        self.status_label.config(text="停止中", fg="orange")
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        try:
            flask_process.terminate()
            flask_process.join(timeout=3)
            if flask_process.is_alive():
                flask_process.kill()
                flask_process.join()
            flask_process = None
            self.status_label.config(text=f"已停止  |  端口: {self.current_port}", fg="gray")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.port_entry.config(state="normal")
            self.check_port_btn.config(state="normal")
            self.log_message("NetAssist 服务已停止")
            # 重置端口状态标签
            self.port_status_label.config(text="未测端口", fg="gray")
            self._update_tray_menu()
        except Exception as e:
            self.log_message(f"停止异常: {e}", "ERROR")
            self.status_label.config(text="停止失败", fg="red")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.port_entry.config(state="normal")
            self.check_port_btn.config(state="normal")

    def quit_app(self, icon=None, item=None):
        if flask_process and flask_process.is_alive():
            self.stop_netassist()
        if tray_icon:
            tray_icon.stop()
        self.master.quit()
        self.master.destroy()
        sys.exit(0)

# ---------- 主入口 ----------
def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('NetAssist.FlaskManager.v1')
    except:
        pass
    multiprocessing.freeze_support()
    global root_window
    root_window = tk.Tk()
    app_gui = NetAssistGUI(root_window)
    def run_tray():
        if tray_icon:
            tray_icon.run()
    threading.Thread(target=run_tray, daemon=True).start()
    root_window.mainloop()

if __name__ == "__main__":
    main()
