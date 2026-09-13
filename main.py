import os
import sys
import time
import threading
from threading import Thread


def fix_console_encoding():
    """콘솔 UTF-8 설정

    한글 Windows 기본 코드페이지가 cp949라 배너의 블록 문자(U+2588)를
    인코딩 못 하고 UnicodeEncodeError로 죽음. 파일로 리다이렉트해도 마찬가지
    """
    try:
        from ctypes import windll
        windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


fix_console_encoding()


def enable_dpi_awareness():
    """창 좌표를 물리 픽셀로 받으려면 DPI 인식이 켜져 있어야 함

    실패하면 배율(125% 등)만큼 좌표가 축소돼 캡처가 통째로 어긋남
    예외 대신 실패 코드를 반환하므로 반환값을 꼭 볼 것
    """
    from ctypes import windll, c_void_p, c_int

    try:
        fn = getattr(windll.user32, 'SetProcessDpiAwarenessContext', None)
        if fn is not None:
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
            # HANDLE이 64비트라 argtypes 없이 넘기면 -4가 32비트로 잘려
            # 조용히 실패함
            fn.argtypes = [c_void_p]
            fn.restype = c_int
            if fn(c_void_p(-4)):
                return 'per-monitor v2'
    except Exception:
        pass

    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2, 성공하면 S_OK(0)
        if windll.shcore.SetProcessDpiAwareness(2) == 0:
            return 'per-monitor'
    except Exception:
        pass

    try:
        if windll.user32.SetProcessDPIAware():
            return 'system'
    except Exception:
        pass

    return None


# 다른 모듈이 창/DC 만들기 전에 제일 먼저
DPI_MODE = enable_dpi_awareness()

import pynput
from win32gui import FindWindow, GetClientRect, ClientToScreen

from hacks import (bruteforce, casinofingerprint, casinokeypad, cayofingerprint,
                   cayovoltage, hostnumber)
from hacks._util import (FocusLost, config_summary, save_debug,
                         set_target_window, timing_summary)

WINDOW_TITLE = "Grand Theft Auto V"
TARGET_AR = 16 / 9

_busy = threading.Lock()


def print_banner():
    print('''
██╗░░░░░███████╗░██████╗████████╗███████╗██████╗░  ██╗░░░██╗███████╗██████╗░  ██████╗░░░░░█████╗░
██║░░░░░██╔════╝██╔════╝╚══██╔══╝██╔════╝██╔══██╗  ██║░░░██║██╔════╝██╔══██╗  ╚════██╗░░░██╔══██╗
██║░░░░░█████╗░░╚█████╗░░░░██║░░░█████╗░░██████╔╝  ╚██╗░██╔╝█████╗░░██████╔╝  ░░███╔═╝░░░██║░░██║
██║░░░░░██╔══╝░░░╚═══██╗░░░██║░░░██╔══╝░░██╔══██╗  ░╚████╔╝░██╔══╝░░██╔══██╗  ██╔══╝░░░░░██║░░██║
███████╗███████╗██████╔╝░░░██║░░░███████╗██║░░██║  ░░╚██╔╝░░███████╗██║░░██║  ███████╗██╗╚█████╔╝
╚══════╝╚══════╝╚═════╝░░░░╚═╝░░░╚══════╝╚═╝░░╚═╝  ░░░╚═╝░░░╚══════╝╚═╝░░╚═╝  ╚══════╝╚═╝░╚════╝░
                                                                                          ''')


def print_credits():
    print('''
Made by JUSTDIE
Special thanks to RedHeadEmile
    ''')


def client_bbox(hwnd):
    """테두리/그림자 뺀 실제 렌더 영역"""
    left, top, right, bottom = GetClientRect(hwnd)
    x0, y0 = ClientToScreen(hwnd, (left, top))
    x1, y1 = ClientToScreen(hwnd, (right, bottom))
    return (x0, y0, x1, y1)


def content_bbox(rect):
    """레터박스/필러박스 잘라내고 16:9 화면만 남김

    21:9에선 미니게임 UI가 화면 중앙 16:9에만 그려짐
    검은 띠를 포함한 채로 계산하면 좌표가 전부 어긋남
    """
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return rect

    ar = w / h
    if ar > TARGET_AR + 1e-3:        # 21:9 등, 좌우가 남음
        cw = round(h * TARGET_AR)
        pad = (w - cw) // 2
        return (x0 + pad, y0, x0 + pad + cw, y1)
    if ar < TARGET_AR - 1e-3:        # 16:10, 4:3 등, 위아래가 남음
        ch = round(w / TARGET_AR)
        pad = (h - ch) // 2
        return (x0, y0 + pad, x1, y0 + pad + ch)
    return rect


def resolve_bbox():
    """핫키 누른 시점의 게임 화면 영역. 못 찾으면 None"""
    hwnd = FindWindow(None, WINDOW_TITLE)
    if not hwnd:
        return None
    return content_bbox(client_bbox(hwnd))


def launch(target):
    """핫키 핸들러 생성. bbox는 누를 때마다 새로 계산"""
    def handler():
        if _busy.locked():
            print('[!] 이미 실행 중입니다.')
            return

        hwnd = FindWindow(None, WINDOW_TITLE)
        if not hwnd:
            print(f'[!] "{WINDOW_TITLE}" 창을 찾을 수 없습니다.')
            return

        bbox = content_bbox(client_bbox(hwnd))
        set_target_window(hwnd)

        def run():
            with _busy:
                try:
                    runner = getattr(target, 'main', target)
                    runner(bbox)
                except FocusLost as e:
                    print(f'[!] {e}')
                    print('=============================================')
                except Exception as e:
                    print(f'[!] {type(e).__name__}: {e}')
                    print('=============================================')

        Thread(target=run, daemon=True).start()

    return handler


def debug_dump():
    """지금 보고 있는 화면을 파일로 저장"""
    bbox = resolve_bbox()
    if bbox is None:
        print(f'[!] "{WINDOW_TITLE}" 창을 찾을 수 없습니다.')
        return
    for path in save_debug(bbox):
        print(f'[*] 저장: {path}')
    print('=============================================')


def shutdown():
    print('[*] 종료합니다.')
    # pynput 콜백은 별도 스레드라 sys.exit()으론 프로세스가 안 죽음
    os._exit(0)


def wait_for_window():
    print(f'[*] Searching {WINDOW_TITLE}...')
    while True:
        bbox = resolve_bbox()
        if bbox:
            print(f'[*] {WINDOW_TITLE} Detected!')
            return bbox
        time.sleep(1)


def main():
    print_banner()
    print_credits()

    print(f'[*] DPI awareness: {DPI_MODE or "실패"}')
    print(f'[*] Timing: {timing_summary()}')
    print(f'[*] Config: {config_summary()}')
    if DPI_MODE is None:
        print('[!] DPI 인식 실패 - 배율이 100%가 아니면 좌표가 어긋납니다.')

    bbox = wait_for_window()
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    print(f'[*] Game bbox: {bbox}  ({w}x{h})')
    if h % 8 or w % 8:
        print('[!] 크기가 어중간합니다. 모니터 배율이 100%인지 확인하세요.')
    print('')
    print('[*] F4  : 프로그램 종료')
    print('[*] F5  : 지문 스캐너 (다이아몬드 카지노 습격)')
    print('[*] F6  : 금고 키패드 크래커 (다이아몬드 카지노 습격)')
    print('[*] F7  : 금고 키패드 크래커 2 (코르츠 센터 습격용)')
    print('[*] F8  : 지문 복제기 (카요 페리코 습격)')
    print('[*] F9  : 볼트랩 전압 해킹 (카요 페리코 습격)')
    print('[*] F10 : HackConnect 숫자/IP 찾기 (여러 임무 공용)')
    print('[*] F11 : BruteForce 비밀번호 맞추기 (여러 임무 공용)')
    print('[*] F12 : 인식 화면 저장 (문제 진단용, debug/ 폴더)')
    print('')
    print('[!] 전체화면(Fullscreen) 대신 테두리 없는 창 모드를 쓰세요.')
    print('[!] 화면 캡처가 검게 나오면 이 프로그램을 관리자 권한으로 실행하세요.')
    print('=============================================')

    with pynput.keyboard.GlobalHotKeys({
            '<F4>': shutdown,
            '<F5>': launch(casinofingerprint),
            '<F6>': launch(casinokeypad),
            '<F7>': launch(casinokeypad.main_kortz),
            '<F8>': launch(cayofingerprint),
            '<F9>': launch(cayovoltage),
            '<F10>': launch(hostnumber),
            '<F11>': launch(bruteforce),
            '<F12>': debug_dump}) as h:
        h.join()


if __name__ == "__main__":
    main()
