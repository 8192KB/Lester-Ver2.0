import time

import cv2
import numpy as np

from ._util import (ADAPTIVE_WAIT, DEBUG, KEYPAD_CONFIRM, _env, dump, grab,
                    retry, tap, wait_stable)

tofind = (454, 300, 1080, 830)

# tofind 크롭 기준 노드 격자. 실제 캡처에서 측정
# 예전 좌표는 y가 39px 위, 원 테두리를 찍고 있었음
GRID_X0, GRID_Y0, GRID_STEP = 44, 41, 108
COLS, ROWS = 6, 5

# 채워진 노드 하나가 약 5000px. 글자나 잡티 거르는 용도
MIN_BLOB_AREA = 1500
# 격자 중심에서 이만큼 벗어나면 잘못 읽은 것
MAX_GRID_ERROR = 30

# 커서 정렬용 'w' 횟수. 기본 0 = 안 함
# 다이얼이 위아래로 순환해서 'w'로 맨 위에 보내는 건 불가능
# 예전에 넣었던 w x4가 1행 -> 5 -> 4 -> 3 -> 2행으로 밀어버려서
# 전 열이 한 칸씩 어긋났었음
HOME_PRESSES = int(_env('LESTER_HOME', 0))
# 암기 단계 끝나기를 기다리는 최대 시간(초)
PHASE_TIMEOUT = 12.0
# 패턴 사라진 뒤 여유. 너무 일찍 누르면 통째로 씹힘
PHASE_SETTLE = _env('LESTER_PHASE_SETTLE', 0.6)

# 커서는 분홍(241,121,125) 원점. 정규화 화면에서 면적 약 310
CURSOR_MIN_AREA, CURSOR_MAX_AREA = 120, 900

# 커서를 못 찾았을 때 직전 판 마지막 행을 재사용할 시간(초)
# 판이 끝나고 바로 다음 판이 시작되면 커서가 그 자리에 남아 있음
CARRY_WINDOW = _env('LESTER_CARRY_WINDOW', 25.0)

# (마지막 행, 끝난 시각)
_last_end = None

# 디버그 오버레이용 격자 좌표
length = [GRID_X0 + GRID_STEP * c for c in range(COLS)]
height = [GRID_Y0 + GRID_STEP * r for r in range(ROWS)]


def cyan_mask(img):
    """청록 노드만 남긴 이진 이미지

    예전엔 마스크를 그레이스케일로 되돌려 215로 이진화했는데
    청록(38,235,234) 휘도가 176이라 그 임계값을 넘을 수가 없었음
    inRange가 이미 0/255를 주니 그대로 씀
    """
    hsv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2HSV)
    return cv2.inRange(hsv, np.array([50, 50, 50]), np.array([96, 255, 255]))


def find_nodes(mask):
    """켜진 노드를 (열, 행)으로 변환. 이상하면 None"""
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

    numbers = [None] * COLS
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] < MIN_BLOB_AREA:
            continue

        cx, cy = centroids[i]
        col = round((cx - GRID_X0) / GRID_STEP)
        row = round((cy - GRID_Y0) / GRID_STEP)
        if not (0 <= col < COLS and 0 <= row < ROWS):
            return None
        if (abs(cx - (GRID_X0 + GRID_STEP * col)) > MAX_GRID_ERROR
                or abs(cy - (GRID_Y0 + GRID_STEP * row)) > MAX_GRID_ERROR):
            return None
        if numbers[col] is not None:      # 한 열에 두 개는 불가능
            return None
        numbers[col] = row + 1

    if any(v is None for v in numbers):
        return None
    return numbers


def read_numbers(bbox):
    return find_nodes(cyan_mask(grab(bbox).crop(tofind)))


def wait_for_input_phase(bbox, timeout=PHASE_TIMEOUT):
    """암기 패턴이 사라질 때까지 대기"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        mask = cyan_mask(grab(bbox).crop(tofind))
        if find_nodes(mask) is None:
            return True
        time.sleep(0.1)

    print('[!] 입력 단계 전환을 감지하지 못했습니다. 그대로 진행합니다.')
    return False


def pink_mask(img):
    """커서/실패 표식으로 쓰이는 분홍 원점만 남김"""
    hsv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2HSV)
    low = cv2.inRange(hsv, np.array([0, 60, 120]), np.array([12, 255, 255]))
    high = cv2.inRange(hsv, np.array([168, 60, 120]), np.array([179, 255, 255]))
    return low | high


def find_cursor_row(mask):
    """커서가 놓인 행(1~5). 확실하지 않으면 None

    커서와 실패 표식은 색도 크기도 같음
    판 시작 직후엔 실패 표식이 없으니 분홍 원점이 딱 하나일 때만 인정
    """
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

    found = []
    for i in range(1, count):
        if not (CURSOR_MIN_AREA <= stats[i, cv2.CC_STAT_AREA] <= CURSOR_MAX_AREA):
            continue

        cx, cy = centroids[i]
        col = round((cx - GRID_X0) / GRID_STEP)
        row = round((cy - GRID_Y0) / GRID_STEP)
        if not (0 <= col < COLS and 0 <= row < ROWS):
            continue
        if (abs(cx - (GRID_X0 + GRID_STEP * col)) > MAX_GRID_ERROR
                or abs(cy - (GRID_Y0 + GRID_STEP * row)) > MAX_GRID_ERROR):
            continue
        found.append((col, row + 1))

    if len(found) != 1:
        return None
    col, row = found[0]
    # 판이 막 시작됐으면 커서는 1열에 있어야 함
    return row if col == 0 else None


def start_row(bbox):
    """시작 행. 화면 > 직전 판 기억 > 기본값 순"""
    row = find_cursor_row(pink_mask(grab(bbox).crop(tofind)))
    if row is not None:
        return row, '화면에서 커서 인식'

    if _last_end:
        last_row, when = _last_end
        elapsed = time.time() - when
        if elapsed <= CARRY_WINDOW:
            return last_row, f'직전 판 마지막 행 ({elapsed:.0f}초 전)'

    return 1, '기본값(맨 위)'


def confirm(bbox):
    """'return' 뒤 다음 칸으로 넘어갈 때까지 대기"""
    if ADAPTIVE_WAIT:
        # 판정이 안 되면 KEYPAD_CONFIRM까지 기다리므로 고정 대기보다 나빠지진 않음
        wait_stable(bbox, tofind, timeout=KEYPAD_CONFIRM, floor=KEYPAD_CONFIRM * 0.35)
    else:
        time.sleep(KEYPAD_CONFIRM)


def build_moves(numbers, begin=1):
    """커서가 begin 행에 있다고 보고 키 순서 생성

    한 열을 확정하면 커서는 그 행에 남은 채 다음 열로 넘어감
    그래서 각 열의 이동량은 직전 열 값과의 차이
    """
    keyboardgo = []
    prev = begin

    for value in numbers:
        if value == prev:
            keyboardgo.append('1')          # 이동 없음, 판에 영향 없는 키
        elif value < prev:
            keyboardgo.extend(['w'] * (prev - value))
        else:
            keyboardgo.extend(['s'] * (value - prev))
        keyboardgo.append('return')
        prev = value

    return keyboardgo


def calculate(numbers, bbox, begin=1):
    global _last_end

    keyboardgo = build_moves(numbers, begin)
    print('-', keyboardgo)

    for key in keyboardgo:
        tap(key)
        if key == 'return':
            confirm(bbox)

    # 다음 판이 바로 이어지면 커서가 마지막 행에 남음
    _last_end = (numbers[-1], time.time())
    print('[*] END')


def solve(bbox, force_first_row=False):
    if force_first_row:
        print('[*] 금고 키패드 크래커 2 (코르츠 센터 습격용)')
    else:
        print('[*] 금고 키패드 크래커 (다이아몬드 카지노 습격)')

    if DEBUG:
        dump(bbox, 'casino_keypad')

    numbers = retry(lambda: read_numbers(bbox))
    if numbers is None:
        print(f'[!] 청록색 패턴을 인식하지 못했습니다. - bbox {bbox}')
        dump(bbox, 'casino_keypad_fail')
        print('=============================================')
        return

    print('-', numbers)

    wait_for_input_phase(bbox)
    time.sleep(PHASE_SETTLE)

    # 코르츠 센터 습격은 2회차도 항상 1행에서 시작한다.
    # 카지노 습격은 화면의 커서 또는 직전 판의 마지막 행을 이어 쓴다.
    if force_first_row:
        begin, how = 1, '코르츠 센터: 매회 1행에서 시작'
    else:
        begin, how = start_row(bbox)
    print(f'- 시작 행: {begin} ({how})')

    for _ in range(HOME_PRESSES):
        tap('w')

    calculate(numbers, bbox, begin)
    print('=============================================')


def main(bbox):
    solve(bbox)


def main_kortz(bbox):
    solve(bbox, force_first_row=True)
