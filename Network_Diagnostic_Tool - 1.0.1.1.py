import sys
import os
import json
import threading
import subprocess
import re
import socket
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QPushButton, QTextEdit, QLabel, QTabWidget,
    QProgressBar, QSplitter, QGridLayout, QMessageBox, QComboBox,
    QLineEdit, QCheckBox, QSpinBox, QFormLayout, QFileDialog
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QSettings, QTimer,
    QSize, QRect, QMetaObject, Q_ARG
)
from PyQt5.QtGui import (
    QFont, QIcon, QTextCursor, QColor, QPalette
)


class CommandWorker(QThread):
    """命令执行工作线程"""
    output_signal = pyqtSignal(str, str)  # 信号: (命令名, 输出)
    progress_signal = pyqtSignal(int, str)  # 信号: (进度值, 状态信息)
    finished_signal = pyqtSignal(str, bool)  # 信号: (命令名, 是否成功)

    def __init__(self, command_name: str, command: str, args: list = None):
        super().__init__()
        self.command_name = command_name
        self.command = command
        self.args = args or []
        self.is_running = True

    def run(self):
        """执行命令"""
        try:
            self.progress_signal.emit(10, f"开始执行 {self.command_name}...")
            
            # 构建完整命令
            full_command = [self.command] + self.args
            
            self.progress_signal.emit(30, "正在执行命令...")
            
            # 执行命令并捕获输出
            process = subprocess.Popen(
                full_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                shell=True,
                text=True,
                encoding='gbk'  # Windows中文编码
            )
            
            stdout, stderr = process.communicate()
            return_code = process.returncode
            
            self.progress_signal.emit(70, "处理输出结果...")
            
            # 输出结果
            output = ""
            if stdout:
                output += stdout
            if stderr:
                output += f"\n错误信息:\n{stderr}"
            
            if return_code == 0:
                output = f"✓ {self.command_name} 执行成功\n" + \
                        "="*50 + f"\n{output}\n" + "="*50
            else:
                output = f"✗ {self.command_name} 执行失败 (代码: {return_code})\n" + \
                        "="*50 + f"\n{output}\n" + "="*50
            
            self.output_signal.emit(self.command_name, output)
            self.progress_signal.emit(100, f"{self.command_name} 完成")
            self.finished_signal.emit(self.command_name, return_code == 0)
            
        except Exception as e:
            error_msg = f"执行 {self.command_name} 时发生错误:\n{str(e)}"
            self.output_signal.emit(self.command_name, error_msg)
            self.progress_signal.emit(100, f"{self.command_name} 失败")
            self.finished_signal.emit(self.command_name, False)
        finally:
            self.is_running = False

    def stop(self):
        """停止命令执行"""
        self.is_running = False
        self.terminate()


class SettingsManager:
    """设置管理器"""
    def __init__(self):
        self.settings_file = Path.home() / ".network_tool_settings.json"
        self.default_settings = {
            "window_geometry": None,
            "window_state": None,
            "recent_commands": [],
            "auto_save": True,
            "auto_scroll": True,
            "max_history": 100,
            "timeout": 30,
            "theme": "light",
            "font_size": 10,
            "output_format": "text",
            "custom_host": "www.baidu.com",
            "custom_port": "80",
            "ping_count": "4",
            "ping_size": "32",
            "trace_hop": "30",
            "dns_server": "8.8.8.8"
        }
        self.settings = self.load_settings()

    def load_settings(self) -> Dict[str, Any]:
        """加载设置"""
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 合并默认设置和已保存的设置
                    settings = self.default_settings.copy()
                    settings.update(loaded)
                    return settings
        except Exception as e:
            print(f"加载设置失败: {e}")
        return self.default_settings.copy()

    def save_settings(self, settings: Dict[str, Any]):
        """保存设置"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            self.settings = settings
        except Exception as e:
            print(f"保存设置失败: {e}")

    def get(self, key: str, default=None) -> Any:
        """获取设置值"""
        return self.settings.get(key, default)

    def set(self, key: str, value: Any):
        """设置值"""
        self.settings[key] = value
        if self.settings.get("auto_save", True):
            self.save_settings(self.settings)

    def add_recent_command(self, command: str):
        """添加最近使用的命令"""
        if "recent_commands" not in self.settings:
            self.settings["recent_commands"] = []
        
        recent = self.settings["recent_commands"]
        if command in recent:
            recent.remove(command)
        recent.insert(0, command)
        
        # 保持最近命令数量
        max_history = self.settings.get("max_history", 100)
        if len(recent) > max_history:
            recent = recent[:max_history]
        
        self.settings["recent_commands"] = recent
        self.save_settings(self.settings)


class NetworkDiagnosticTool(QMainWindow):
    """网络诊断工具主窗口"""
    
    def __init__(self):
        super().__init__()
        self.settings_manager = SettingsManager()
        self.workers = {}  # 存储正在运行的线程
        self.output_buffers = {}  # 存储输出缓冲
        self.init_ui()
        self.load_settings()
        self.setup_commands()

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle('网络故障诊断工具 v1.0')
        self.setMinimumSize(1000, 700)
        
        # 设置图标
        icon_path = "icon.ico"
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # 基础诊断标签页
        self.setup_basic_diagnosis_tab()
        
        # 高级工具标签页
        self.setup_advanced_tools_tab()
        
        # 自定义命令标签页
        self.setup_custom_commands_tab()
        
        # 设置标签页
        self.setup_settings_tab()
        
        # 输出区域
        self.setup_output_area(main_layout)
        
        # 状态栏
        self.setup_status_bar()
        
        # 应用样式
        self.apply_style()

    def setup_basic_diagnosis_tab(self):
        """设置基础诊断标签页"""
        basic_tab = QWidget()
        layout = QGridLayout(basic_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # 网络连接测试组
        conn_group = QGroupBox("网络连接测试")
        conn_layout = QGridLayout(conn_group)
        
        self.btn_ping = QPushButton("Ping 测试")
        self.btn_ping.clicked.connect(lambda: self.execute_command("ping"))
        conn_layout.addWidget(self.btn_ping, 0, 0)
        
        self.btn_tracert = QPushButton("路由追踪")
        self.btn_tracert.clicked.connect(lambda: self.execute_command("tracert"))
        conn_layout.addWidget(self.btn_tracert, 0, 1)
        
        self.btn_nslookup = QPushButton("DNS 查询")
        self.btn_nslookup.clicked.connect(lambda: self.execute_command("nslookup"))
        conn_layout.addWidget(self.btn_nslookup, 1, 0)
        
        self.btn_netstat = QPushButton("网络连接状态")
        self.btn_netstat.clicked.connect(lambda: self.execute_command("netstat"))
        conn_layout.addWidget(self.btn_netstat, 1, 1)
        
        layout.addWidget(conn_group, 0, 0, 1, 2)
        
        # IP配置信息组
        ip_group = QGroupBox("IP配置信息")
        ip_layout = QVBoxLayout(ip_group)
        
        self.btn_ipconfig = QPushButton("显示IP配置 (ipconfig /all)")
        self.btn_ipconfig.clicked.connect(lambda: self.execute_command("ipconfig"))
        ip_layout.addWidget(self.btn_ipconfig)
        
        self.btn_ip_release = QPushButton("释放IP地址 (ipconfig /release)")
        self.btn_ip_release.clicked.connect(lambda: self.execute_command("ipconfig_release"))
        ip_layout.addWidget(self.btn_ip_release)
        
        self.btn_ip_renew = QPushButton("续订IP地址 (ipconfig /renew)")
        self.btn_ip_renew.clicked.connect(lambda: self.execute_command("ipconfig_renew"))
        ip_layout.addWidget(self.btn_ip_renew)
        
        layout.addWidget(ip_group, 1, 0)
        
        # 网络诊断组
        diag_group = QGroupBox("网络诊断")
        diag_layout = QVBoxLayout(diag_group)
        
        self.btn_diag = QPushButton("Windows网络诊断")
        self.btn_diag.clicked.connect(lambda: self.execute_command("diagnose"))
        diag_layout.addWidget(self.btn_diag)
        
        self.btn_reset_winsock = QPushButton("重置Winsock目录")
        self.btn_reset_winsock.clicked.connect(lambda: self.execute_command("winsock"))
        diag_layout.addWidget(self.btn_reset_winsock)
        
        self.btn_flush_dns = QPushButton("清除DNS缓存")
        self.btn_flush_dns.clicked.connect(lambda: self.execute_command("flushdns"))
        diag_layout.addWidget(self.btn_flush_dns)
        
        layout.addWidget(diag_group, 1, 1)
        
        # 快速测试组
        quick_group = QGroupBox("快速测试")
        quick_layout = QVBoxLayout(quick_group)
        
        self.btn_test_all = QPushButton("执行全面网络测试")
        self.btn_test_all.clicked.connect(self.run_comprehensive_test)
        quick_layout.addWidget(self.btn_test_all)
        
        self.btn_stop_all = QPushButton("停止所有测试")
        self.btn_stop_all.clicked.connect(self.stop_all_commands)
        self.btn_stop_all.setEnabled(False)
        quick_layout.addWidget(self.btn_stop_all)
        
        layout.addWidget(quick_group, 2, 0, 1, 2)
        
        self.tab_widget.addTab(basic_tab, "基础诊断")

    def setup_advanced_tools_tab(self):
        """设置高级工具标签页"""
        advanced_tab = QWidget()
        layout = QGridLayout(advanced_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # 端口扫描组
        port_group = QGroupBox("端口扫描")
        port_layout = QFormLayout(port_group)
        
        self.edit_host = QLineEdit()
        self.edit_host.setText(self.settings_manager.get("custom_host", "www.baidu.com"))
        port_layout.addRow("目标主机:", self.edit_host)
        
        self.edit_port = QLineEdit()
        self.edit_port.setText(self.settings_manager.get("custom_port", "80"))
        port_layout.addRow("目标端口:", self.edit_port)
        
        self.btn_port_scan = QPushButton("扫描端口")
        self.btn_port_scan.clicked.connect(self.scan_port)
        port_layout.addRow(self.btn_port_scan)
        
        layout.addWidget(port_group, 0, 0)
        
        # 网络信息组
        info_group = QGroupBox("网络信息")
        info_layout = QVBoxLayout(info_group)
        
        self.btn_arp = QPushButton("显示ARP缓存")
        self.btn_arp.clicked.connect(lambda: self.execute_command("arp"))
        info_layout.addWidget(self.btn_arp)
        
        self.btn_route = QPushButton("显示路由表")
        self.btn_route.clicked.connect(lambda: self.execute_command("route"))
        info_layout.addWidget(self.btn_route)
        
        self.btn_getmac = QPushButton("显示MAC地址")
        self.btn_getmac.clicked.connect(lambda: self.execute_command("getmac"))
        info_layout.addWidget(self.btn_getmac)
        
        layout.addWidget(info_group, 0, 1)
        
        # Ping高级选项组
        ping_group = QGroupBox("Ping高级选项")
        ping_layout = QFormLayout(ping_group)
        
        self.spin_ping_count = QSpinBox()
        self.spin_ping_count.setRange(1, 100)
        self.spin_ping_count.setValue(int(self.settings_manager.get("ping_count", 4)))
        ping_layout.addRow("Ping次数:", self.spin_ping_count)
        
        self.spin_ping_size = QSpinBox()
        self.spin_ping_size.setRange(1, 65500)
        self.spin_ping_size.setValue(int(self.settings_manager.get("ping_size", 32)))
        ping_layout.addRow("数据包大小(字节):", self.spin_ping_size)
        
        self.btn_ping_advanced = QPushButton("自定义Ping测试")
        self.btn_ping_advanced.clicked.connect(self.advanced_ping)
        ping_layout.addRow(self.btn_ping_advanced)
        
        layout.addWidget(ping_group, 1, 0)
        
        # Tracert高级选项组
        trace_group = QGroupBox("路由追踪选项")
        trace_layout = QFormLayout(trace_group)
        
        self.spin_trace_hop = QSpinBox()
        self.spin_trace_hop.setRange(1, 255)
        self.spin_trace_hop.setValue(int(self.settings_manager.get("trace_hop", 30)))
        trace_layout.addRow("最大跳数:", self.spin_trace_hop)
        
        self.edit_dns_server = QLineEdit()
        self.edit_dns_server.setText(self.settings_manager.get("dns_server", "8.8.8.8"))
        trace_layout.addRow("DNS服务器:", self.edit_dns_server)
        
        self.btn_trace_advanced = QPushButton("高级路由追踪")
        self.btn_trace_advanced.clicked.connect(self.advanced_tracert)
        trace_layout.addRow(self.btn_trace_advanced)
        
        layout.addWidget(trace_group, 1, 1)
        
        self.tab_widget.addTab(advanced_tab, "高级工具")

    def setup_custom_commands_tab(self):
        """设置自定义命令标签页"""
        custom_tab = QWidget()
        layout = QVBoxLayout(custom_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # 命令输入组
        input_group = QGroupBox("自定义命令")
        input_layout = QFormLayout(input_group)
        
        self.edit_custom_cmd = QLineEdit()
        self.edit_custom_cmd.setPlaceholderText("输入命令，如: ping -n 5 www.google.com")
        input_layout.addRow("命令:", self.edit_custom_cmd)
        
        btn_layout = QHBoxLayout()
        self.btn_run_custom = QPushButton("运行命令")
        self.btn_run_custom.clicked.connect(self.run_custom_command)
        btn_layout.addWidget(self.btn_run_custom)
        
        self.btn_save_custom = QPushButton("保存命令")
        self.btn_save_custom.clicked.connect(self.save_custom_command)
        btn_layout.addWidget(self.btn_save_custom)
        
        input_layout.addRow(btn_layout)
        
        layout.addWidget(input_group)
        
        # 保存的命令组
        saved_group = QGroupBox("已保存的命令")
        saved_layout = QVBoxLayout(saved_group)
        
        self.combo_saved_commands = QComboBox()
        self.load_saved_commands()
        saved_layout.addWidget(self.combo_saved_commands)
        
        btn_saved_layout = QHBoxLayout()
        self.btn_run_saved = QPushButton("运行选中命令")
        self.btn_run_saved.clicked.connect(self.run_saved_command)
        btn_saved_layout.addWidget(self.btn_run_saved)
        
        self.btn_delete_saved = QPushButton("删除选中命令")
        self.btn_delete_saved.clicked.connect(self.delete_saved_command)
        btn_saved_layout.addWidget(self.btn_delete_saved)
        
        saved_layout.addLayout(btn_saved_layout)
        
        layout.addWidget(saved_group)
        
        self.tab_widget.addTab(custom_tab, "自定义命令")

    def setup_settings_tab(self):
        """设置设置标签页"""
        settings_tab = QWidget()
        layout = QFormLayout(settings_tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 界面设置
        self.check_auto_scroll = QCheckBox("输出自动滚动")
        self.check_auto_scroll.setChecked(self.settings_manager.get("auto_scroll", True))
        layout.addRow("界面设置:", self.check_auto_scroll)
        
        self.check_auto_save = QCheckBox("自动保存设置")
        self.check_auto_save.setChecked(self.settings_manager.get("auto_save", True))
        layout.addRow("", self.check_auto_save)
        
        # 字体大小
        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(8, 20)
        self.spin_font_size.setValue(self.settings_manager.get("font_size", 10))
        layout.addRow("输出字体大小:", self.spin_font_size)
        
        # 历史记录数量
        self.spin_max_history = QSpinBox()
        self.spin_max_history.setRange(10, 1000)
        self.spin_max_history.setValue(self.settings_manager.get("max_history", 100))
        layout.addRow("最大历史记录:", self.spin_max_history)
        
        # 命令超时时间
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(5, 300)
        self.spin_timeout.setValue(self.settings_manager.get("timeout", 30))
        layout.addRow("命令超时(秒):", self.spin_timeout)
        
        # 主题选择
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["浅色主题", "深色主题"])
        theme = self.settings_manager.get("theme", "light")
        self.combo_theme.setCurrentIndex(0 if theme == "light" else 1)
        layout.addRow("界面主题:", self.combo_theme)
        
        # 输出格式
        self.combo_output_format = QComboBox()
        self.combo_output_format.addItems(["文本格式", "HTML格式"])
        output_format = self.settings_manager.get("output_format", "text")
        self.combo_output_format.setCurrentIndex(0 if output_format == "text" else 1)
        layout.addRow("输出格式:", self.combo_output_format)
        
        # 按钮组
        btn_layout = QHBoxLayout()
        self.btn_save_settings = QPushButton("保存设置")
        self.btn_save_settings.clicked.connect(self.save_current_settings)
        btn_layout.addWidget(self.btn_save_settings)
        
        self.btn_reset_settings = QPushButton("恢复默认")
        self.btn_reset_settings.clicked.connect(self.reset_settings)
        btn_layout.addWidget(self.btn_reset_settings)
        
        self.btn_export_log = QPushButton("导出日志")
        self.btn_export_log.clicked.connect(self.export_log)
        btn_layout.addWidget(self.btn_export_log)
        
        layout.addRow(btn_layout)
        
        self.tab_widget.addTab(settings_tab, "设置")

    def setup_output_area(self, main_layout):
        """设置输出区域"""
        # 输出文本框
        self.text_output = QTextEdit()
        self.text_output.setReadOnly(True)
        self.text_output.setFont(QFont("Consolas", self.settings_manager.get("font_size", 10)))
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        # 进度标签
        self.label_progress = QLabel("就绪")
        
        # 添加到主布局
        main_layout.addWidget(self.text_output, 3)
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.label_progress)
        main_layout.addLayout(progress_layout)

    def setup_status_bar(self):
        """设置状态栏"""
        self.status_bar = self.statusBar()
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
        
        # 网络状态指示器
        self.network_status = QLabel("●")
        self.network_status.setStyleSheet("color: green; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.network_status)
        
        # 命令计数
        self.command_count = QLabel("命令: 0")
        self.status_bar.addPermanentWidget(self.command_count)
        
        # 更新时间
        self.update_time = QLabel("")
        self.status_bar.addPermanentWidget(self.update_time)
        
        # 定时更新状态栏
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status_bar)
        self.status_timer.start(1000)

    def apply_style(self):
        """应用样式"""
        if self.settings_manager.get("theme", "light") == "dark":
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #2b2b2b;
                }
                QTextEdit {
                    background-color: #1e1e1e;
                    color: #d4d4d4;
                    border: 1px solid #555;
                }
                QGroupBox {
                    color: #aaa;
                    border: 2px solid #555;
                    border-radius: 5px;
                    margin-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }
                QPushButton {
                    background-color: #555;
                    color: white;
                    border: 1px solid #777;
                    padding: 5px;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #666;
                }
                QPushButton:pressed {
                    background-color: #444;
                }
                QPushButton:disabled {
                    background-color: #333;
                    color: #777;
                }
                QLineEdit, QComboBox, QSpinBox {
                    background-color: #333;
                    color: white;
                    border: 1px solid #555;
                    padding: 3px;
                }
                QProgressBar {
                    border: 1px solid #555;
                    border-radius: 3px;
                    text-align: center;
                }
                QProgressBar::chunk {
                    background-color: #4CAF50;
                    border-radius: 3px;
                }
            """)
        else:
            self.setStyleSheet("""
                QGroupBox {
                    border: 2px solid #cccccc;
                    border-radius: 5px;
                    margin-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }
                QPushButton {
                    background-color: #f0f0f0;
                    border: 1px solid #cccccc;
                    padding: 5px;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
                QPushButton:disabled {
                    background-color: #f8f8f8;
                    color: #aaaaaa;
                }
                QProgressBar {
                    border: 1px solid #cccccc;
                    border-radius: 3px;
                    text-align: center;
                }
                QProgressBar::chunk {
                    background-color: #4CAF50;
                    border-radius: 3px;
                }
            """)

    def setup_commands(self):
        """设置命令字典"""
        self.commands = {
            "ping": {
                "command": "ping",
                "args": ["-n", "4", self.edit_host.text() if hasattr(self, 'edit_host') else "www.baidu.com"]
            },
            "tracert": {
                "command": "tracert",
                "args": ["-h", "30", self.edit_host.text() if hasattr(self, 'edit_host') else "www.baidu.com"]
            },
            "nslookup": {
                "command": "nslookup",
                "args": [self.edit_host.text() if hasattr(self, 'edit_host') else "www.baidu.com"]
            },
            "netstat": {
                "command": "netstat",
                "args": ["-ano"]
            },
            "ipconfig": {
                "command": "ipconfig",
                "args": ["/all"]
            },
            "ipconfig_release": {
                "command": "ipconfig",
                "args": ["/release"]
            },
            "ipconfig_renew": {
                "command": "ipconfig",
                "args": ["/renew"]
            },
            "diagnose": {
                "command": "netsh",
                "args": ["wlan", "show", "all"]
            },
            "winsock": {
                "command": "netsh",
                "args": ["winsock", "reset"]
            },
            "flushdns": {
                "command": "ipconfig",
                "args": ["/flushdns"]
            },
            "arp": {
                "command": "arp",
                "args": ["-a"]
            },
            "route": {
                "command": "route",
                "args": ["print"]
            },
            "getmac": {
                "command": "getmac",
                "args": ["/v"]
            }
        }

    def execute_command(self, command_name: str):
        """执行命令"""
        # 更新命令参数
        self.update_command_args()
        
        if command_name not in self.commands:
            self.append_output(f"错误: 未知命令 '{command_name}'")
            return
        
        # 添加历史记录
        self.settings_manager.add_recent_command(command_name)
        
        # 创建并启动工作线程
        cmd_info = self.commands[command_name]
        worker = CommandWorker(
            command_name,
            cmd_info["command"],
            cmd_info["args"]
        )
        
        # 连接信号
        worker.output_signal.connect(self.append_output)
        worker.progress_signal.connect(self.update_progress)
        worker.finished_signal.connect(self.on_command_finished)
        
        # 存储线程引用
        self.workers[command_name] = worker
        
        # 更新UI状态
        self.btn_stop_all.setEnabled(True)
        self.update_command_counter()
        
        # 启动线程
        worker.start()
        
        # 显示开始消息
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.append_output(f"[{timestamp}] 开始执行: {command_name}")

    def append_output(self, command_name: str, text: str):
        """追加输出到文本框"""
        cursor = self.text_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        # 设置文本颜色
        if "成功" in text or "✓" in text:
            self.text_output.setTextColor(QColor(0, 128, 0))  # 绿色
        elif "失败" in text or "✗" in text or "错误" in text:
            self.text_output.setTextColor(QColor(255, 0, 0))  # 红色
        else:
            self.text_output.setTextColor(QColor(0, 0, 0) if self.settings_manager.get("theme") == "light" else QColor(255, 255, 255))
        
        # 插入文本
        cursor.insertText(text + "\n\n")
        
        # 自动滚动
        if self.check_auto_scroll.isChecked():
            self.text_output.setTextCursor(cursor)
            self.text_output.ensureCursorVisible()

    def update_progress(self, value: int, text: str):
        """更新进度条"""
        self.progress_bar.setValue(value)
        self.label_progress.setText(text)

    def on_command_finished(self, command_name: str, success: bool):
        """命令完成处理"""
        # 移除线程引用
        if command_name in self.workers:
            del self.workers[command_name]
        
        # 更新UI状态
        if not self.workers:
            self.btn_stop_all.setEnabled(False)
            self.update_progress(0, "就绪")
        
        # 更新状态栏
        self.update_status_bar()
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        status = "成功" if success else "失败"
        self.append_output(f"[{timestamp}] {command_name} 执行{status}")

    def run_comprehensive_test(self):
        """执行全面网络测试"""
        test_sequence = [
            "flushdns",
            "ipconfig",
            "ping",
            "tracert",
            "nslookup",
            "netstat"
        ]
        
        for cmd in test_sequence:
            self.execute_command(cmd)

    def stop_all_commands(self):
        """停止所有命令"""
        for command_name, worker in list(self.workers.items()):
            worker.stop()
            del self.workers[command_name]
        
        self.btn_stop_all.setEnabled(False)
        self.append_output("系统", "已停止所有命令执行")
        self.update_progress(0, "已停止")

    def scan_port(self):
        """扫描端口"""
        host = self.edit_host.text()
        port = self.edit_port.text()
        
        try:
            port = int(port)
            self.update_progress(30, f"正在扫描 {host}:{port}...")
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            
            result = sock.connect_ex((host, port))
            
            if result == 0:
                output = f"✓ 端口 {port} 在 {host} 上开放\n"
                output += f"服务可能为: {self.get_service_name(port)}"
            else:
                output = f"✗ 端口 {port} 在 {host} 上关闭或无法访问"
            
            sock.close()
            
            self.append_output("端口扫描", output)
            self.update_progress(100, "端口扫描完成")
            
        except Exception as e:
            self.append_output("端口扫描", f"扫描失败: {str(e)}")
            self.update_progress(100, "扫描失败")

    def get_service_name(self, port: int) -> str:
        """获取常见端口服务名称"""
        common_ports = {
            20: "FTP数据",
            21: "FTP控制",
            22: "SSH",
            23: "Telnet",
            25: "SMTP",
            53: "DNS",
            80: "HTTP",
            110: "POP3",
            143: "IMAP",
            443: "HTTPS",
            3306: "MySQL",
            3389: "远程桌面",
            8080: "HTTP代理"
        }
        return common_ports.get(port, "未知服务")

    def advanced_ping(self):
        """高级Ping测试"""
        host = self.edit_host.text()
        count = self.spin_ping_count.value()
        size = self.spin_ping_size.value()
        
        # 更新命令并执行
        self.commands["ping"]["args"] = ["-n", str(count), "-l", str(size), host]
        self.execute_command("ping")

    def advanced_tracert(self):
        """高级路由追踪"""
        host = self.edit_host.text()
        hops = self.spin_trace_hop.value()
        
        self.commands["tracert"]["args"] = ["-h", str(hops), host]
        self.execute_command("tracert")

    def run_custom_command(self):
        """运行自定义命令"""
        command = self.edit_custom_cmd.text().strip()
        if not command:
            QMessageBox.warning(self, "警告", "请输入命令")
            return
        
        # 分割命令和参数
        parts = command.split()
        if not parts:
            return
        
        cmd_name = parts[0]
        args = parts[1:] if len(parts) > 1 else []
        
        worker = CommandWorker(f"自定义: {command}", cmd_name, args)
        worker.output_signal.connect(self.append_output)
        worker.progress_signal.connect(self.update_progress)
        worker.finished_signal.connect(self.on_command_finished)
        
        self.workers[f"custom_{command}"] = worker
        worker.start()
        
        self.btn_stop_all.setEnabled(True)

    def save_custom_command(self):
        """保存自定义命令"""
        command = self.edit_custom_cmd.text().strip()
        if not command:
            QMessageBox.warning(self, "警告", "请输入命令")
            return
        
        # 添加到设置
        saved = self.settings_manager.get("saved_commands", [])
        if command not in saved:
            saved.append(command)
            self.settings_manager.set("saved_commands", saved)
            
            # 更新下拉框
            self.combo_saved_commands.addItem(command)
            
            QMessageBox.information(self, "成功", "命令已保存")

    def load_saved_commands(self):
        """加载保存的命令"""
        saved = self.settings_manager.get("saved_commands", [])
        self.combo_saved_commands.addItems(saved)

    def run_saved_command(self):
        """运行保存的命令"""
        command = self.combo_saved_commands.currentText()
        if command:
            self.edit_custom_cmd.setText(command)
            self.run_custom_command()

    def delete_saved_command(self):
        """删除保存的命令"""
        command = self.combo_saved_commands.currentText()
        if command:
            # 从设置中移除
            saved = self.settings_manager.get("saved_commands", [])
            if command in saved:
                saved.remove(command)
                self.settings_manager.set("saved_commands", saved)
            
            # 从下拉框中移除
            index = self.combo_saved_commands.currentIndex()
            self.combo_saved_commands.removeItem(index)
            
            QMessageBox.information(self, "成功", "命令已删除")

    def save_current_settings(self):
        """保存当前设置"""
        settings = {
            "auto_scroll": self.check_auto_scroll.isChecked(),
            "auto_save": self.check_auto_save.isChecked(),
            "font_size": self.spin_font_size.value(),
            "max_history": self.spin_max_history.value(),
            "timeout": self.spin_timeout.value(),
            "theme": "light" if self.combo_theme.currentIndex() == 0 else "dark",
            "output_format": "text" if self.combo_output_format.currentIndex() == 0 else "html",
            "custom_host": self.edit_host.text() if hasattr(self, 'edit_host') else "",
            "custom_port": self.edit_port.text() if hasattr(self, 'edit_port') else "",
            "ping_count": self.spin_ping_count.value(),
            "ping_size": self.spin_ping_size.value(),
            "trace_hop": self.spin_trace_hop.value(),
            "dns_server": self.edit_dns_server.text() if hasattr(self, 'edit_dns_server') else ""
        }
        
        self.settings_manager.save_settings(settings)
        
        # 应用新设置
        self.text_output.setFont(QFont("Consolas", self.spin_font_size.value()))
        self.apply_style()
        
        QMessageBox.information(self, "成功", "设置已保存")

    def reset_settings(self):
        """重置设置"""
        reply = QMessageBox.question(self, "确认", "确定要恢复默认设置吗？",
                                   QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.settings_manager.save_settings(self.settings_manager.default_settings)
            self.load_settings()
            QMessageBox.information(self, "成功", "设置已恢复为默认值")

    def export_log(self):
        """导出日志"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", "network_diagnostic_log.txt",
            "文本文件 (*.txt);;所有文件 (*.*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.text_output.toPlainText())
                QMessageBox.information(self, "成功", f"日志已导出到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

    def update_command_args(self):
        """更新命令参数"""
        if hasattr(self, 'edit_host'):
            host = self.edit_host.text()
            dns_server = self.edit_dns_server.text() if hasattr(self, 'edit_dns_server') else "8.8.8.8"
            
            self.commands["ping"]["args"] = ["-n", "4", host]
            self.commands["tracert"]["args"] = ["-h", "30", host]
            self.commands["nslookup"]["args"] = [host, dns_server]

    def update_command_counter(self):
        """更新命令计数器"""
        count = len(self.workers)
        self.command_count.setText(f"运行中: {count}")

    def update_status_bar(self):
        """更新状态栏"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.update_time.setText(current_time)
        
        # 更新网络状态
        if self.workers:
            self.network_status.setText("● 运行中")
            self.network_status.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.network_status.setText("● 就绪")
            self.network_status.setStyleSheet("color: green; font-weight: bold;")

    def load_settings(self):
        """加载设置"""
        # 窗口几何信息
        geometry = self.settings_manager.get("window_geometry")
        if geometry:
            self.setGeometry(*geometry)
        else:
            self.showMaximized()
        
        # 窗口状态
        state = self.settings_manager.get("window_state")
        if state:
            self.restoreState(state)

    def save_window_state(self):
        """保存窗口状态"""
        geometry = [
            self.x(), self.y(),
            self.width(), self.height()
        ]
        self.settings_manager.set("window_geometry", geometry)
        self.settings_manager.set("window_state", self.saveState())

    def closeEvent(self, event):
        """关闭事件处理"""
        self.save_window_state()
        self.stop_all_commands()
        super().closeEvent(event)


def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setApplicationName("网络故障诊断工具")
    
    # 设置高DPI支持
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # 创建并显示窗口
    window = NetworkDiagnosticTool()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()