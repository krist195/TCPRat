import os
import socket
import struct
import sys
import json
import subprocess
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QWidget, QVBoxLayout, QCheckBox
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread


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
HOST = env.get('HOST', '0.0.0.0')
PORT = int(env.get('PORT', env.get('SERVER_PORT', '........'))) # Порт сервера

active_windows = []


def recv_all(sock, length):
    data = b""
    while len(data) < length:
        try:
            packet = sock.recv(length - len(data))
        except BlockingIOError:
            continue
        except OSError as e:
            print(f"Ошибка recv_all: {e}")
            return None
        if not packet:
            return None
        data += packet
    return data



class FrameReceiver(QThread):
    frame_received = pyqtSignal(QImage)

    def __init__(self, client_socket):
        super().__init__()
        self.client_socket = client_socket

    def run(self):
        try:
            while True:
                header = recv_all(self.client_socket, 4)
                if not header:
                    break
                frame_length = struct.unpack('!I', header)[0]
                if frame_length <= 0:
                    break

                payload = recv_all(self.client_socket, frame_length)
                if not payload:
                    break

                payload_type = payload[0]
                body = payload[1:]
                if payload_type == 1:
                    image = QImage()
                    if image.loadFromData(body, "JPEG"):
                        self.frame_received.emit(image)
                else:
                    # Ignore any non-image payloads from client
                    continue
        except Exception as e:
            print(f"Ошибка при получении данных: {e}")
        finally:
            self.client_socket.close()


class ScreenShareWindow(QMainWindow):
    def __init__(self, client_socket):
        super().__init__()
        self.setWindowTitle("Screen Share")
        self.setGeometry(100, 100, 900, 700)

        self.mouse_enabled = True
        self.keyboard_enabled = True

        self.control_widget = QWidget(self)
        self.layout = QVBoxLayout(self.control_widget)
        self.control_widget.setLayout(self.layout)

        self.checkbox_mouse = QCheckBox("Mouse control", self)
        self.checkbox_mouse.setChecked(True)
        self.checkbox_keyboard = QCheckBox("Keyboard control", self)
        self.checkbox_keyboard.setChecked(True)
        self.layout.addWidget(self.checkbox_mouse)
        self.layout.addWidget(self.checkbox_keyboard)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMouseTracking(True)
        self.label.setFocusPolicy(Qt.StrongFocus)
        self.layout.addWidget(self.label)

        self.setCentralWidget(self.control_widget)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.control_widget.setFocus()

        self.last_image = None
        self.receiver = FrameReceiver(client_socket)
        self.receiver.frame_received.connect(self.update_image)
        self.receiver.finished.connect(self.on_connection_closed)
        self.receiver.start()
        self.show()

    def update_image(self, image):
        self.last_image = image
        pixmap = QPixmap.fromImage(image)
        self.label.setPixmap(pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def map_to_image_coords(self, pos):
        pixmap = self.label.pixmap()
        if pixmap is None or self.last_image is None:
            return None

        label_size = self.label.size()
        pixmap_size = pixmap.size()
        x_offset = (label_size.width() - pixmap_size.width()) / 2
        y_offset = (label_size.height() - pixmap_size.height()) / 2
        local_pos = self.label.mapFrom(self, pos)
        x = local_pos.x() - x_offset
        y = local_pos.y() - y_offset
        if x < 0 or y < 0 or x >= pixmap_size.width() or y >= pixmap_size.height():
            return None

        image_x = int(x * self.last_image.width() / pixmap_size.width())
        image_y = int(y * self.last_image.height() / pixmap_size.height())
        return image_x, image_y

    def send_command(self, command):
        try:
            payload = json.dumps(command).encode('utf-8')
            packet = struct.pack('!I', len(payload) + 1) + b'\x02' + payload
            self.receiver.client_socket.sendall(packet)
        except Exception as e:
            print(f"Ошибка отправки команды: {e}")

    def mouseMoveEvent(self, event):
        if self.checkbox_mouse.isChecked():
            coords = self.map_to_image_coords(event.pos())
            if coords is not None:
                self.send_command({
                    'cmd': 'move',
                    'x': coords[0],
                    'y': coords[1],
                })
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if self.checkbox_mouse.isChecked():
            coords = self.map_to_image_coords(event.pos())
            if coords is not None:
                button = None
                if event.button() == Qt.LeftButton:
                    button = 'left'
                elif event.button() == Qt.RightButton:
                    button = 'right'
                elif event.button() == Qt.MiddleButton:
                    button = 'middle'
                if button:
                    self.send_command({
                        'cmd': 'button',
                        'action': 'press',
                        'button': button,
                        'x': coords[0],
                        'y': coords[1],
                    })
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.checkbox_mouse.isChecked():
            coords = self.map_to_image_coords(event.pos())
            if coords is not None:
                button = None
                if event.button() == Qt.LeftButton:
                    button = 'left'
                elif event.button() == Qt.RightButton:
                    button = 'right'
                elif event.button() == Qt.MiddleButton:
                    button = 'middle'
                if button:
                    self.send_command({
                        'cmd': 'button',
                        'action': 'release',
                        'button': button,
                        'x': coords[0],
                        'y': coords[1],
                    })
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.checkbox_keyboard.isChecked():
            key_value = event.text() or ''
            key_name = event.key()
            command = {
                'cmd': 'key',
                'action': 'press',
                'key': key_value,
                'key_code': key_name,
            }
            self.send_command(command)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if self.checkbox_keyboard.isChecked():
            key_value = event.text() or ''
            key_name = event.key()
            command = {
                'cmd': 'key',
                'action': 'release',
                'key': key_value,
                'key_code': key_name,
            }
            self.send_command(command)
        super().keyReleaseEvent(event)

    def on_connection_closed(self):
        print("Соединение закрыто.")
        try:
            active_windows.remove(self)
        except ValueError:
            pass
        self.close()


def accept_connection(server_socket):
    try:
        client_socket, addr = server_socket.accept()
    except BlockingIOError:
        return
    except OSError:
        return

    client_socket.setblocking(True)
    print(f"Подключение от: {addr}")
    window = ScreenShareWindow(client_socket)
    active_windows.append(window)




def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    server_socket.setblocking(False)
    print(f"Сервер запущен на {HOST}:{PORT}")

    app = QApplication([])
    timer = QTimer()
    timer.timeout.connect(lambda: accept_connection(server_socket))
    timer.start(50)

    app.aboutToQuit.connect(lambda: server_socket.close())

    try:
        return app.exec_()
    except KeyboardInterrupt:
        print("Остановка сервера по запросу пользователя...")
        server_socket.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
