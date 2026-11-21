#!/usr/bin/env python3
"""Windows MSS持续抓屏工具。仅保存原始PNG和时间信息，不加载OCR。"""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import sys
import threading
import time
import uuid

VERSION = "1.0.0"


@dataclass(frozen=True)
class Area:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self):
        if any(type(value) is not int for value in asdict(self).values()) or self.width <= 0 or self.height <= 0:
            raise ValueError("窗口内容区域必须有有效的像素尺寸")

    def fits(self, desktop):
        return (self.left >= desktop["left"] and self.top >= desktop["top"]
                and self.left + self.width <= desktop["left"] + desktop["width"]
                and self.top + self.height <= desktop["top"] + desktop["height"])


def validate_settings(duration, fps, interval):
    import math
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (duration, fps, interval)):
        raise ValueError("时间和频率必须是有效数字")
    if not 1 <= duration <= 7200 or not 1 <= fps <= 60 or not 0 <= interval <= 300:
        raise ValueError("时长须为1～7200秒，抓屏频率1～60 FPS，保存间隔0～300秒")


def png_size(path):
    with Path(path).open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("没有生成有效PNG")
    return struct.unpack(">II", header[16:24])


class WindowsAPI:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("此截图工具需要在Windows上运行")
        import ctypes as ct
        from ctypes import wintypes as wt
        self.ct, self.wt = ct, wt
        self.user = ct.WinDLL("user32", use_last_error=True)
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.callback_type = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        declarations = {
            "EnumWindows": ([self.callback_type, wt.LPARAM], wt.BOOL),
            "IsWindow": ([wt.HWND], wt.BOOL), "IsWindowVisible": ([wt.HWND], wt.BOOL),
            "IsIconic": ([wt.HWND], wt.BOOL),
            "GetWindowTextLengthW": ([wt.HWND], ct.c_int),
            "GetWindowTextW": ([wt.HWND, wt.LPWSTR, ct.c_int], ct.c_int),
            "GetClientRect": ([wt.HWND, ct.POINTER(wt.RECT)], wt.BOOL),
            "ClientToScreen": ([wt.HWND, ct.POINTER(wt.POINT)], wt.BOOL),
            "GetWindowThreadProcessId": ([wt.HWND, ct.POINTER(wt.DWORD)], wt.DWORD),
            "GetForegroundWindow": ([], wt.HWND),
            "GetAncestor": ([wt.HWND, wt.UINT], wt.HWND),
            "SetForegroundWindow": ([wt.HWND], wt.BOOL),
            "RegisterHotKey": ([wt.HWND, ct.c_int, wt.UINT, wt.UINT], wt.BOOL),
            "UnregisterHotKey": ([wt.HWND, ct.c_int], wt.BOOL),
            "GetMessageW": ([ct.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT], ct.c_int),
            "PeekMessageW": ([ct.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT], wt.BOOL),
            "PostThreadMessageW": ([wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM], wt.BOOL),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.user, name); fn.argtypes = args; fn.restype = result
        self.kernel.GetCurrentThreadId.restype = wt.DWORD
        self.dpi_mode = self.enable_dpi()

    def enable_dpi(self):
        ct = self.ct
        try:
            fn = self.user.SetProcessDpiAwarenessContext
            fn.argtypes = [ct.c_void_p]; fn.restype = self.wt.BOOL
            if fn(ct.c_void_p(-4)):
                return "PerMonitorV2"
            if ct.get_last_error() == 5:
                return "manifest/already-configured"
        except AttributeError:
            pass
        try:
            ct.WinDLL("shcore").SetProcessDpiAwareness(2)
            return "PerMonitor"
        except (OSError, AttributeError):
            self.user.SetProcessDPIAware()
            return "SystemAware"

    def title(self, hwnd):
        length = min(4096, self.user.GetWindowTextLengthW(hwnd) + 1)
        buffer = self.ct.create_unicode_buffer(max(1, length))
        self.user.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def area(self, hwnd):
        if not self.user.IsWindow(hwnd):
            raise ValueError("所选窗口已经关闭，请重新选择")
        if self.user.IsIconic(hwnd):
            raise ValueError("游戏窗口已最小化，请先恢复窗口")
        rect, point = self.wt.RECT(), self.wt.POINT(0, 0)
        if not self.user.GetClientRect(hwnd, self.ct.byref(rect)) or not self.user.ClientToScreen(hwnd, self.ct.byref(point)):
            raise self.ct.WinError(self.ct.get_last_error())
        return Area(point.x, point.y, rect.right - rect.left, rect.bottom - rect.top)

    def foreground(self, hwnd):
        foreground = self.user.GetForegroundWindow()
        return foreground == hwnd or self.user.GetAncestor(foreground, 3) == hwnd

    def dpi(self, hwnd):
        try:
            fn = self.user.GetDpiForWindow
            fn.argtypes = [self.wt.HWND]; fn.restype = self.wt.UINT
            return int(fn(hwnd))
        except AttributeError:
            return None

    def windows(self, exclude_pid=None):
        found = []
        @self.callback_type
        def callback(hwnd, _):
            if not self.user.IsWindowVisible(hwnd):
                return True
            pid = self.wt.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
            if pid.value == exclude_pid:
                return True
            title = self.title(hwnd)
            if title:
                try:
                    area = self.area(hwnd)
                except (ValueError, OSError):
                    return True
                if area.width >= 100 and area.height >= 100:
                    found.append({"hwnd": int(hwnd), "title": title, "area": area})
            return True
        if not self.user.EnumWindows(callback, 0):
            raise self.ct.WinError(self.ct.get_last_error())
        return sorted(found, key=lambda row: ("洛克" not in row["title"], row["title"]))


class Hotkeys(threading.Thread):
    def __init__(self, api, events):
        super().__init__(daemon=True)
        self.api, self.events, self.thread_id = api, events, None
        self.ready = threading.Event()

    def run(self):
        api = self.api; self.thread_id = api.kernel.GetCurrentThreadId(); registered = []
        try:
            for ident, vk in [(8, 0x77), (9, 0x78)]:
                if api.user.RegisterHotKey(None, ident, 0x4000, vk):
                    registered.append(ident)
                else:
                    self.events.put(("hotkey_warning", f"F{ident}已被其他程序占用，可使用窗口按钮"))
            msg = api.wt.MSG()
            api.user.PeekMessageW(api.ct.byref(msg), None, 0, 0, 0)
            self.ready.set()
            while api.user.GetMessageW(api.ct.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:
                    self.events.put(("hotkey", int(msg.wParam)))
        finally:
            self.ready.set()
            for ident in registered:
                api.user.UnregisterHotKey(None, ident)

    def close(self):
        self.ready.wait(1)
        if self.thread_id:
            self.api.user.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)


class CaptureSession:
    def __init__(self, api, hwnd, output, duration=600, fps=20, interval=1,
                 events=None, single=False, require_foreground=True):
        validate_settings(duration, fps, interval)
        self.api, self.hwnd, self.output = api, hwnd, Path(output)
        self.duration, self.fps, self.interval = duration, fps, interval
        self.events = events if events is not None else queue.SimpleQueue()
        self.single, self.require_foreground = single, require_foreground
        self.stop = threading.Event(); self.manual = threading.Event(); self.capture_done = threading.Event()
        self.pending = queue.Queue(maxsize=3)
        self.lock = threading.Lock()
        self.stats = {"captured": 0, "saved": 0, "save_queue_dropped": 0,
                      "paused_checks": 0, "capture_total_ms": 0, "failure": None}
        self.folder = None; self.last_frame = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def snapshot(self):
        with self.lock:
            return dict(self.stats)

    def fail(self, error):
        with self.lock:
            if self.stats["failure"] is None:
                self.stats["failure"] = str(error)
        self.stop.set()

    def writer(self):
        try:
            from mss.tools import to_png
            with (self.folder / "frames.jsonl").open("w", encoding="utf-8") as log:
                while not self.capture_done.is_set() or not self.pending.empty():
                    try:
                        shot, record = self.pending.get(timeout=.1)
                    except queue.Empty:
                        continue
                    target = self.folder / record["file"]
                    temporary = target.with_suffix(".png.part")
                    try:
                        to_png(shot.rgb, shot.size, level=1, output=str(temporary))
                        temporary.replace(target)
                        log.write(json.dumps(record, ensure_ascii=False) + "\n"); log.flush()
                        self.last_frame = record
                        with self.lock:
                            self.stats["saved"] += 1
                    finally:
                        if temporary.exists():
                            temporary.unlink()
        except Exception as exc:
            self.fail(exc)

    def run(self):
        started = time.perf_counter(); writer = None; source = None
        try:
            from mss import MSS
            self.output.mkdir(parents=True, exist_ok=True)
            ident = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
            self.folder = self.output / (("single_" if self.single else "session_") + ident)
            self.folder.mkdir(parents=True)
            source = {"version": VERSION, "window_title": self.api.title(self.hwnd),
                      "window_handle": self.hwnd, "started_at": datetime.now(timezone.utc).isoformat(),
                      "target_capture_fps": self.fps, "save_interval_s": self.interval,
                      "planned_duration_s": self.duration, "dpi_awareness": self.api.dpi_mode,
                      "output_format": "PNG lossless, original client pixels; no resize"}
            self.events.put(("folder", str(self.folder)))
            writer = threading.Thread(target=self.writer, daemon=True); writer.start()
            with MSS() as sct:
                desktop = dict(sct.monitors[0]); next_tick = started; next_save = started; last_update = 0
                while not self.stop.is_set():
                    now = time.perf_counter()
                    if now - started >= self.duration:
                        break
                    if not self.api.user.IsWindow(self.hwnd):
                        raise ValueError("所选游戏窗口已关闭，监控结束")
                    if self.require_foreground and (not self.api.foreground(self.hwnd) or self.api.user.IsIconic(self.hwnd)):
                        with self.lock:
                            self.stats["paused_checks"] += 1
                        self.events.put(("paused", "游戏未在前台，已暂停抓图；切回游戏后继续"))
                        self.stop.wait(.5); next_tick = time.perf_counter(); continue
                    area = self.api.area(self.hwnd)
                    if not area.fits(desktop):
                        raise ValueError("游戏内容超出屏幕范围，请把窗口完整移回屏幕后重新开始")
                    before = time.perf_counter(); shot = sct.grab(asdict(area)); captured_at = time.perf_counter()
                    with self.lock:
                        self.stats["captured"] += 1
                        sequence = self.stats["captured"]
                        self.stats["capture_total_ms"] += (captured_at - before) * 1000
                    manual = self.manual.is_set()
                    if manual:
                        self.manual.clear()
                    if manual or self.interval == 0 or captured_at >= next_save or self.single:
                        if shutil.disk_usage(self.folder).free < 512 * 1024 * 1024:
                            raise OSError("剩余磁盘空间不足512MB，已停止；已保存图片保留")
                        elapsed = captured_at - started
                        record = {"file": f"frame_{sequence:07d}_{elapsed:010.3f}s.png", "capture_sequence": sequence,
                                  "elapsed_s": round(elapsed, 6), "captured_at": datetime.now(timezone.utc).isoformat(),
                                  "client_rect": asdict(area), "window_dpi": self.api.dpi(self.hwnd),
                                  "reason": "manual" if manual else "periodic"}
                        if self.single:
                            offset = ((area.height // 2) * area.width + area.width // 2) * 4
                            raw = shot.raw
                            record["center_rgb"] = [raw[offset + 2], raw[offset + 1], raw[offset]]
                        try:
                            self.pending.put_nowait((shot, record))
                        except queue.Full:
                            with self.lock:
                                self.stats["save_queue_dropped"] += 1
                        if self.interval > 0 and captured_at >= next_save:
                            next_save = started + (int((captured_at - started) / self.interval) + 1) * self.interval
                    if captured_at - last_update >= .5:
                        self.events.put(("progress", {**self.snapshot(), "elapsed_s": round(captured_at - started, 1),
                                                       "width": area.width, "height": area.height}))
                        last_update = captured_at
                    if self.single:
                        break
                    next_tick = max(next_tick + 1 / self.fps, captured_at)
                    self.stop.wait(max(0, next_tick - time.perf_counter()))
        except Exception as exc:
            self.fail(exc)
        finally:
            self.capture_done.set()
            if writer:
                writer.join()
            elapsed = time.perf_counter() - started
            result = {**(source or {}), **self.snapshot(), "elapsed_s": round(elapsed, 6),
                      "last_frame": self.last_frame, "stopped_at": datetime.now(timezone.utc).isoformat()}
            result["average_grab_ms"] = round(result["capture_total_ms"] / max(1, result["captured"]), 3)
            result["observed_capture_fps_including_pauses"] = round(result["captured"] / max(.001, elapsed), 3)
            if self.folder:
                try:
                    (self.folder / "session.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except OSError as exc:
                    self.fail(exc)
                    result["failure"] = self.snapshot()["failure"]
            self.events.put(("finished", result))


def run_self_test(api, output):
    import tkinter as tk
    root = tk.Tk(); root.title("RocoCapture native self-test"); root.geometry("640x360+100+100")
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, background="#204060", highlightthickness=0); canvas.pack(fill="both", expand=True)
    canvas.create_text(30, 30, text="MSS native pixel test", fill="white", anchor="nw")
    root.update(); root.lift(); api.user.SetForegroundWindow(root.winfo_id()); root.update()
    time.sleep(.2); root.update()
    try:
        windows = [w for w in api.windows() if w["title"] == root.title()]
        if len(windows) != 1:
            raise RuntimeError("无法定位自测窗口")
        session = CaptureSession(api, windows[0]["hwnd"], output, duration=5, fps=10, interval=0,
                                 single=True, require_foreground=False)
        session.thread.start(); deadline = time.monotonic() + 20
        while session.thread.is_alive() and time.monotonic() < deadline:
            root.update(); time.sleep(.01)
        if session.thread.is_alive():
            session.stop.set(); raise TimeoutError("原生截图自测超时")
        stats = session.snapshot()
        if stats["failure"] or stats["saved"] != 1:
            raise RuntimeError(str(stats))
        size = png_size(session.folder / session.last_frame["file"])
        if size != (640, 360) or session.last_frame["center_rgb"] != [32, 64, 96]:
            raise RuntimeError(f"截图像素不符：{size}, {session.last_frame}")
        continuous = CaptureSession(api, windows[0]["hwnd"], output, duration=1.5, fps=20,
                                    interval=.25, require_foreground=False)
        continuous.thread.start(); deadline = time.monotonic() + 20
        while continuous.thread.is_alive() and time.monotonic() < deadline:
            root.update(); time.sleep(.01)
        if continuous.thread.is_alive():
            continuous.stop.set(); raise TimeoutError("持续抓屏自测超时")
        stats = continuous.snapshot()
        if stats["failure"] or stats["captured"] < 5 or stats["saved"] < 2:
            raise RuntimeError(f"持续抓屏失败：{stats}")
        if png_size(continuous.folder / continuous.last_frame["file"]) != (640, 360):
            raise RuntimeError("持续截图尺寸不符")
        output.mkdir(parents=True, exist_ok=True)
        (output / "self-test.json").write_text(json.dumps({"ok": True, "size": list(size),
            "center_rgb": session.last_frame["center_rgb"], "session": str(session.folder),
            "continuous_capture": stats}, indent=2) + "\n")
    finally:
        root.destroy()


class App:
    def __init__(self, root, api):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        self.tk, self.ttk, self.dialog, self.messagebox = tk, ttk, filedialog, messagebox
        self.root, self.api = root, api
        self.events = queue.SimpleQueue(); self.session = None; self.closing = False
        self.windows = []; self.last_folder = None
        root.title("RocoCapture · 游戏窗口持续截图"); root.geometry("660x420"); root.minsize(620, 400)
        self.output = tk.StringVar(value=str(Path.home() / "Pictures" / "RocoCaptures"))
        self.duration = tk.StringVar(value="10"); self.fps = tk.StringVar(value="20"); self.interval = tk.StringVar(value="1")
        self.status = tk.StringVar(value="选择游戏窗口，开始后工具自动最小化；F9开始/停止，F8额外留图。")
        panel = ttk.Frame(root, padding=16); panel.pack(fill="both", expand=True); panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="1. 选择游戏窗口（仅截取内容，不含标题栏）").grid(row=0, column=0, sticky="w")
        row = ttk.Frame(panel); row.grid(row=1, column=0, sticky="ew", pady=(6, 12)); row.columnconfigure(0, weight=1)
        self.combo = ttk.Combobox(row, state="readonly"); self.combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="刷新窗口", command=self.refresh).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(panel, text="2. 选择保存位置").grid(row=2, column=0, sticky="w")
        row = ttk.Frame(panel); row.grid(row=3, column=0, sticky="ew", pady=(6, 12)); row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.output).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="选择目录", command=self.choose).grid(row=0, column=1, padx=(8, 0))
        row = ttk.Frame(panel); row.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        for i, (label, var, a, b) in enumerate([("时长(分钟)", self.duration, 1, 120),
                                               ("抓屏FPS", self.fps, 1, 60),
                                               ("保存间隔(秒)", self.interval, 0, 300)]):
            ttk.Label(row, text=label).grid(row=0, column=i, sticky="w", padx=(0, 18))
            ttk.Spinbox(row, from_=a, to=b, textvariable=var, width=13).grid(row=1, column=i, padx=(0, 18))
        ttk.Label(panel, text="PNG保留原始尺寸。间隔0＝尝试保存每帧；默认1秒一张，10分钟约600张。\n保存繁忙会跳过并计数。游戏切到后台时暂停抓图，切回继续；计时仍继续。",
                  wraplength=610).grid(row=5, column=0, sticky="w", pady=(0, 12))
        row = ttk.Frame(panel); row.grid(row=6, column=0, sticky="ew")
        self.start_button = ttk.Button(row, text="开始监控 F9", command=self.toggle); self.start_button.pack(side="left")
        ttk.Button(row, text="立即留图 F8", command=self.capture_one).pack(side="left", padx=8)
        ttk.Button(row, text="打开图片目录", command=self.open_folder).pack(side="left")
        ttk.Label(panel, textvariable=self.status, wraplength=610).grid(row=7, column=0, sticky="w", pady=14)
        self.hotkeys = Hotkeys(api, self.events); self.hotkeys.start()
        root.protocol("WM_DELETE_WINDOW", self.close); self.refresh(); root.after(80, self.poll)

    def refresh(self):
        try:
            self.windows = self.api.windows(exclude_pid=os.getpid())
            self.combo["values"] = [f"{w['title']}  [{w['area'].width}×{w['area'].height}]" for w in self.windows]
            if self.windows:self.combo.current(0)
        except Exception as exc:self.status.set(str(exc))

    def choose(self):
        folder = self.dialog.askdirectory(initialdir=self.output.get(), title="选择截图保存目录")
        if folder:self.output.set(folder)

    def toggle(self):
        if self.busy():
            self.session.stop.set(); self.status.set("正在停止并保存最后几张图片……")
        else:self.start(False)

    def capture_one(self):
        if self.busy():self.session.manual.set()
        else:self.start(True)

    def busy(self):
        return self.session is not None and (self.session.thread.is_alive() or not self.session.capture_done.is_set())

    def start(self, single):
        try:
            i = self.combo.current()
            if not 0 <= i < len(self.windows):raise ValueError("请先选择一个游戏窗口")
            hwnd = self.windows[i]["hwnd"]; self.api.area(hwnd)
            duration, fps, interval = float(self.duration.get()) * 60, float(self.fps.get()), float(self.interval.get())
            validate_settings(duration, fps, interval)
            folder = Path(self.output.get()).expanduser()
            self.session = CaptureSession(self.api, hwnd, folder, duration=duration, fps=fps, interval=interval,
                                          events=self.events, single=single)
            self.start_button.configure(text="停止监控 F9"); self.status.set("正在切换到游戏并开始抓图……")
            self.root.iconify(); self.api.user.SetForegroundWindow(hwnd)
            self.root.after(350, self.session.thread.start)
        except Exception as exc:
            self.root.deiconify(); self.messagebox.showerror("未能开始截图", str(exc))

    def open_folder(self):
        try:
            folder = self.last_folder or Path(self.output.get()).expanduser()
            Path(folder).mkdir(parents=True, exist_ok=True); os.startfile(str(folder))
        except OSError as exc:self.messagebox.showerror("无法打开图片目录", str(exc))

    def close(self):
        self.closing = True
        if self.session:self.session.stop.set()
        self.hotkeys.close()

    def poll(self):
        try:
            while True:
                name, data = self.events.get_nowait()
                if name == "hotkey":
                    if data == 8:self.capture_one()
                    elif data == 9:self.toggle()
                elif name == "folder":self.last_folder = Path(data)
                elif name == "progress":
                    self.status.set(f"监控中 {data['elapsed_s']}秒｜{data['width']}×{data['height']}｜抓到{data['captured']}帧｜保存{data['saved']}张｜保存队列跳过{data['save_queue_dropped']}帧")
                elif name in ("paused", "hotkey_warning"):self.status.set(data)
                elif name == "finished":
                    self.start_button.configure(text="开始监控 F9")
                    self.status.set(f"已结束：抓到{data['captured']}帧，保存{data['saved']}张；平均抓屏{data['average_grab_ms']}毫秒。目录：{self.last_folder}")
                    if data["failure"] and not self.closing:
                        self.root.deiconify(); self.messagebox.showerror("截图已停止", data["failure"])
        except queue.Empty:pass
        if self.closing and not self.busy():self.root.destroy()
        else:self.root.after(80, self.poll)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Windows构建时验证实际窗口和PNG像素")
    parser.add_argument("--output", type=Path, default=Path(".cache/capture_self_test"))
    args = parser.parse_args()
    try:
        api = WindowsAPI()
        if args.self_test:
            run_self_test(api, args.output); return
        import tkinter as tk
        root = tk.Tk(); App(root, api); root.mainloop()
    except Exception as exc:
        if args.self_test:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "self-test-error.txt").write_text(str(exc), encoding="utf-8")
        elif sys.platform == "win32":
            from tkinter import messagebox
            messagebox.showerror("RocoCapture", str(exc))
        elif sys.stderr:
            print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
