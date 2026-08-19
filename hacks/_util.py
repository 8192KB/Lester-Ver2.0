"""캡처, 샘플링, 키 입력, 재시도 공용 헬퍼"""

import os
import sys
import time

import keyboard
import numpy as np
from PIL import ImageGrab


def _app_dir():
    """exe(또는 스크립트)가 놓인 폴더"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_config():
    """exe 옆 lester.ini 읽기. `이름 = 값` 형식, #은 주석"""
    path = os.path.join(_app_dir(), 'lester.ini')
    values = {}
    try:
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if '=' in line:
                    name, _, value = line.partition('=')
                    values[name.strip().lower()] = value.strip()
    except OSError:
        return values, None
    return values, path


CONFIG, CONFIG_PATH = _load_config()


def _env(name, default):
    """환경변수 > lester.ini > 기본값 순.

    LESTER_KEY_HOLD 는 ini 에서 key_hold
    """
    raw = os.environ.get(name)
    if raw is None:
        raw = CONFIG.get(name.lower().removeprefix('lester_'))
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        raw = CONFIG.get(name.lower().removeprefix('lester_'))
    if raw is None:
        return default
    return raw.strip().lower() not in ('0', 'false', 'no', 'off', '')


# 전체 속도 배율. 느리게 하려면 2 정도
SLOW = _env('LESTER_SLOW', 1.0)

# 60fps면 한 프레임 16.7ms. press/release가 다른 프레임에 걸리게 벌려둠
# 입력 씹히면 키울 것
KEY_HOLD = _env('LESTER_KEY_HOLD', 0.035) * SLOW
KEY_GAP = _env('LESTER_KEY_GAP', 0.045) * SLOW

# 한 칸 확정 후 다음 칸으로 넘어가는 애니메이션 대기
KEYPAD_CONFIRM = _env('LESTER_KEYPAD_CONFIRM', 1.95) * SLOW
VOLTAGE_CONFIRM = _env('LESTER_VOLTAGE_CONFIRM', 1.3) * SLOW

# 등장 애니메이션 끝날 때까지 다시 읽는 횟수/간격
RETRY_COUNT = 8
RETRY_WAIT = 0.15


# 1이면 실행마다 캡처를 남김
DEBUG = _flag('LESTER_DEBUG')

# 포커스 잃으면 즉시 중단. 끄면 키가 다른 창으로 샘
FOCUS_GUARD = _flag('LESTER_FOCUS_GUARD', True)

# 고정 대기 대신 화면 멈춘 걸 보고 진행 (실험적)
ADAPTIVE_WAIT = _flag('LESTER_ADAPTIVE_WAIT', False)

_target_hwnd = None


class FocusLost(Exception):
    """포커스가 게임 밖으로 나감. 남은 키를 보내면 안 됨"""


def set_target_window(hwnd):
    global _target_hwnd
    _target_hwnd = hwnd


def has_focus():
    if not FOCUS_GUARD or _target_hwnd is None:
        return True
    try:
        from ctypes import windll
        return windll.user32.GetForegroundWindow() == _target_hwnd
    except Exception:
        return True


def check_focus():
    if not has_focus():
        raise FocusLost('게임 창이 활성 상태가 아닙니다. 입력을 중단했습니다.')


def wait_stable(bbox, box=None, timeout=2.5, floor=0.0, settle=0.12, tol=1.5):
    """화면이 멈출 때까지 대기

    고정 시간은 빠른 PC에선 낭비, 느린 PC에선 부족
    계속 움직여서 판정 안 되면 timeout까지 기다리므로 최악이어도 고정 대기와 같음
    """
    start = time.time()
    if floor:
        time.sleep(floor)

    prev = None
    stable_since = None
    while time.time() - start < timeout:
        frame = grab(bbox)
        cur = np.asarray(frame.crop(box) if box else frame, dtype=np.int16)
        if prev is not None and cur.shape == prev.shape:
            if np.abs(cur - prev).mean() < tol:
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since >= settle:
                    return True
            else:
                stable_since = None
        prev = cur
        time.sleep(0.03)
    return False


def dump(bbox, tag):
    """진단용 캡처 한 장. 실패해도 본 동작은 계속"""
    try:
        from datetime import datetime
        os.makedirs('debug', exist_ok=True)
        path = os.path.join('debug', f'{datetime.now().strftime("%H%M%S")}_{tag}.png')
        grab(bbox).save(path)
        print(f'[*] 진단 캡처: {path}')
    except Exception as e:
        print(f'[!] 캡처 저장 실패: {e}')


def timing_summary():
    bits = [f'hold {KEY_HOLD * 1000:.0f}ms', f'gap {KEY_GAP * 1000:.0f}ms',
            f'confirm {KEYPAD_CONFIRM:.2f}s', f'slow x{SLOW:g}']
    if ADAPTIVE_WAIT:
        bits.append('adaptive')
    if not FOCUS_GUARD:
        bits.append('focus-guard OFF')
    return ' / '.join(bits)


def config_summary():
    if CONFIG_PATH:
        return f'{CONFIG_PATH} ({len(CONFIG)}개 항목)'
    return f'{os.path.join(_app_dir(), "lester.ini")} 없음 (기본값 사용)'


def grab(bbox):
    """bbox 캡처 후 1920x1080 좌표계로 정규화"""
    im = ImageGrab.grab(bbox)
    if im.size != (1920, 1080):
        im = im.resize((1920, 1080))
    return im


def sample(img, x, y, radius=1):
    """(x, y) 주변 (2r+1)^2 패치의 중앙값

    픽셀 하나만 보면 리사이즈 보간 때문에 임계값을 넘나듦
    중앙값이면 깨끗할 땐 결과가 같고 튀는 픽셀 하나엔 안 흔들림
    """
    h, w = img.shape[:2]
    y0, y1 = max(0, y - radius), min(h, y + radius + 1)
    x0, x1 = max(0, x - radius), min(w, x + radius + 1)
    return float(np.median(img[y0:y1, x0:x1]))


def tap(key, extra=0.0):
    """키 하나 누르고 뗌. extra는 뒤에 더 기다릴 시간

    누르기 직전마다 포커스 확인. 도중에 알트탭이나 콘솔 클릭으로
    포커스가 넘어가면 남은 키가 엉뚱한 창에 들어가서 판이 꼬임
    """
    check_focus()
    keyboard.press(key)
    time.sleep(KEY_HOLD)
    keyboard.release(key)
    time.sleep(KEY_GAP + extra)


def save_debug(bbox, out_dir='debug'):
    """현재 캡처와 각 모듈이 보는 영역을 파일로 저장

    좌표 어긋났는지 눈으로 볼 때 씀. 저장된 경로 목록 반환
    """
    import os
    from datetime import datetime
    from PIL import ImageDraw

    # 순환 import 피하려고 늦게 불러옴
    from . import casinofingerprint, casinokeypad, cayofingerprint, cayovoltage

    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime('%H%M%S')
    base = grab(bbox).convert('RGB')

    paths = []
    raw = os.path.join(out_dir, f'{stamp}_screen.png')
    base.save(raw)
    paths.append(raw)

    def overlay(name, boxes=(), points=()):
        im = base.copy()
        d = ImageDraw.Draw(im)
        for box in boxes:
            d.rectangle(box, outline=(0, 255, 0), width=2)
        for x, y in points:
            d.ellipse((x - 4, y - 4, x + 4, y + 4), outline=(255, 0, 0), width=2)
        path = os.path.join(out_dir, f'{stamp}_{name}.png')
        im.save(path)
        paths.append(path)

    overlay('casino_fingerprint',
            boxes=[casinofingerprint.tofind] + [p[0] for p in casinofingerprint.parts])
    overlay('cayo_fingerprint',
            boxes=list(cayofingerprint.targets) + list(cayofingerprint.scan))

    kx, ky = casinokeypad.tofind[0], casinokeypad.tofind[1]
    overlay('casino_keypad',
            boxes=[casinokeypad.tofind],
            points=[(kx + x, ky + y)
                    for x in casinokeypad.length for y in casinokeypad.height])

    v = cayovoltage
    volt_points = []
    for xs, ys in ((v.target_number_length_0, v.target_number_height),
                   (v.target_number_length_1, v.target_number_height),
                   (v.target_number_length_2, v.target_number_height),
                   (v.left_number_length, v.left_number_height_0),
                   (v.left_number_length, v.left_number_height_1),
                   (v.left_number_length, v.left_number_height_2),
                   (v.right_symbol_length, v.right_symbol_height_0),
                   (v.right_symbol_length, v.right_symbol_height_1),
                   (v.right_symbol_length, v.right_symbol_height_2)):
        volt_points.extend(zip(xs, ys))
    overlay('cayo_voltage', points=volt_points)

    return paths


def retry(read, attempts=RETRY_COUNT, wait=RETRY_WAIT):
    """read()가 값을 낼 때까지 재시도

    read는 성공하면 값, 아직 못 읽었으면 None이나 KeyError
    전부 실패하면 None
    """
    for i in range(attempts):
        try:
            result = read()
            if result is not None:
                return result
        except KeyError:
            pass
        if i + 1 < attempts:
            time.sleep(wait)
    return None
