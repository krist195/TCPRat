import os
import sys
import subprocess
import shutil
import winreg


def get_persistence_path():
    documents = os.path.join(os.path.expanduser('~'), 'Documents')
    dest_dir = os.path.join(documents, 'MicrosoftServices')
    if os.path.isdir(dest_dir):
        for name in ['client.exe', 'client.py']:
            candidate = os.path.join(dest_dir, name)
            if os.path.exists(candidate):
                return candidate
    return os.path.join(dest_dir, 'client.exe') if not sys.argv[0].endswith('.py') else os.path.join(dest_dir, 'client.py')


def remove_autostart_key():
    key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, 'RAT_Client')
                print('Autorun key removed.')
            except FileNotFoundError:
                print('Autorun key not found.')
    except OSError as e:
        print(f'Failed to remove autorun key: {e}')


def remove_persistence_file():
    path = get_persistence_path()
    try:
        if os.path.exists(path):
            os.remove(path)
            print(f'Removed persistence file: {path}')
        parent = os.path.dirname(path)
        if os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
            print(f'Removed empty folder: {parent}')
    except Exception as e:
        print(f'Failed to remove persistence file: {e}')


def kill_by_name(name):
    try:
        subprocess.run(['taskkill', '/F', '/IM', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f'Tried killing process: {name}')
    except Exception:
        pass


def kill_by_cmdline(pattern):
    try:
        output = subprocess.check_output([
            'wmic', 'process', 'where', f'CommandLine like "%{pattern}%"', 'get', 'ProcessId'
        ], stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        for line in output.splitlines():
            line = line.strip()
            if line.isdigit():
                try:
                    subprocess.run(['taskkill', '/F', '/PID', line], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f'Killed PID {line} for pattern {pattern}')
                except Exception:
                    pass
    except Exception:
        pass


def main():
    print('Removing RAT persistence...')
    remove_autostart_key()
    remove_persistence_file()

    persistence_path = get_persistence_path()
    basename = os.path.basename(persistence_path)
    if basename.lower() == 'client.exe':
        kill_by_name('client.exe')
    else:
        kill_by_cmdline('client.py')
        kill_by_name('python.exe')
        kill_by_name('pythonw.exe')

    print('Cleanup complete.')


if __name__ == '__main__':
    main()
