import cv2
import numpy as np

from ._util import DEBUG, VOLTAGE_CONFIRM, dump, grab, retry, sample, tap

DIGITS_LOOKUP = {
    (1, 1, 1, 0, 1, 1, 1): 0,
    (0, 0, 1, 0, 0, 1, 0): 1,
    (1, 0, 1, 1, 1, 0, 1): 2,
    (1, 0, 1, 1, 0, 1, 1): 3,
    (0, 1, 1, 1, 0, 1, 0): 4,
    (1, 1, 0, 1, 0, 1, 1): 5,
    (1, 1, 0, 1, 1, 1, 1): 6,
    (1, 0, 1, 0, 0, 1, 0): 7,
    (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 1, 0, 1, 1): 9
}

RIGHT_SYMBOLS = {
    (0, 1): 10,
    (1, 0): 2,
    (0, 0): 1
}

moves = {
    (0, 0, 1, 1, 2, 2): ['enter', 'return', 'enter', 'return', 'enter', 'return'], # (1-1) + (2-2) + (3-3)
    (0, 0, 1, 2, 2, 1): ['enter', 'return', 'enter', 's', 'return', 'enter', 'return'], # (1-1) + (2-3) + (3-2)
    (0, 1, 1, 0, 2, 2): ['enter', 's', 'return', 'enter', 'w', 'return', 'enter', 'return'], #(1-2) + (2-1) + (3-3)
    (0, 1, 1, 2, 2, 0): ['enter', 's', 'return', 'enter', 'return', 'enter', 'return'], # (1-2) + (2-3) + (3-1)
    (0, 2, 1, 0, 2, 1): ['enter', 'w', 'return', 'enter', 'w', 'return', 'enter', 'return'], # (1-3) + (2-1) + (3-2)
    (0, 2, 1, 1, 2, 0): ['enter', 'w', 'return', 'enter', 'return', 'enter', 'return'] # (1-3) + (2-2) + (3-1)
}

# target numbers
target_number_height = [123, 137, 137, 154, 173, 173, 195] # target numbers have same height
target_number_length_0 = [865, 849, 881, 865, 849, 881, 865] # first number
target_number_length_1 = [955, 939, 971, 955, 939, 971, 955] # second number
target_number_length_2 = [1043, 1029, 1061, 1043, 1029, 1061, 1043] # third number

# left numbers
left_number_length = [509, 495, 527, 509, 495, 527, 509] # left nubmers have same length
left_number_height_0 = [271, 287, 287, 303, 323, 323, 343] # first number
left_number_height_1 = [507, 522, 522, 540, 557, 557, 579] # second number
left_number_height_2 = [741, 755, 755, 773, 791, 791, 813] # third number

# right symbols
right_symbol_length = [1351, 1349] # right symbols have same length
right_symbol_height_0 = [305, 277] # first symbol
right_symbol_height_1 = [541, 513] # second symbol
right_symbol_height_2 = [775, 747] # third symbol


def pixel_check(x, y, img, dictionary):
    """세그먼트 켜짐/꺼짐을 읽어 사전에서 값 찾기"""
    hints = []
    for i in range(len(next(iter(dictionary)))):
        # 픽셀 하나 말고 주변 패치 중앙값, 리사이즈 보간 대비
        hints.append(1 if sample(img, x[i], y[i]) > 0 else 0)
    return dictionary[tuple(hints)]


def read_state(bbox):
    """목표값 / 좌측 숫자 3개 / 우측 기호 3개"""
    im = grab(bbox)
    gray = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)

    target_number = (
        100 * pixel_check(target_number_length_0, target_number_height, bw, DIGITS_LOOKUP)
        + 10 * pixel_check(target_number_length_1, target_number_height, bw, DIGITS_LOOKUP)
        + pixel_check(target_number_length_2, target_number_height, bw, DIGITS_LOOKUP)
    )
    left_numbers = [
        pixel_check(left_number_length, left_number_height_0, bw, DIGITS_LOOKUP),
        pixel_check(left_number_length, left_number_height_1, bw, DIGITS_LOOKUP),
        pixel_check(left_number_length, left_number_height_2, bw, DIGITS_LOOKUP)
    ]
    right_numbers = [
        pixel_check(right_symbol_length, right_symbol_height_0, bw, RIGHT_SYMBOLS),
        pixel_check(right_symbol_length, right_symbol_height_1, bw, RIGHT_SYMBOLS),
        pixel_check(right_symbol_length, right_symbol_height_2, bw, RIGHT_SYMBOLS)
    ]
    return target_number, left_numbers, right_numbers


def calculate(target_number, left_numbers, right_numbers):
    for combo, keys in moves.items():
        z, x, v, n, k, l = combo
        total = (left_numbers[z] * right_numbers[x]
                 + left_numbers[v] * right_numbers[n]
                 + left_numbers[k] * right_numbers[l])
        if total == target_number:
            print('-', keys)
            for key in keys:
                # 'return'은 정답 확정 애니메이션 끝날 때까지 대기
                tap(key, extra=VOLTAGE_CONFIRM if key == 'return' else 0.0)
            print('[*] END')
            return True

    print('[!] 목표값과 맞는 조합이 없습니다. 화면을 잘못 읽었을 수 있습니다.')
    return False


def main(bbox):
    print('[*] Cayo Voltage Hack')

    if DEBUG:
        dump(bbox, 'cayo_voltage')

    state = retry(lambda: read_state(bbox))
    if state is None:
        print(f'[!] 숫자를 인식하지 못했습니다. - bbox {bbox}')
        dump(bbox, 'cayo_voltage_fail')
        print('=============================================')
        return

    target_number, left_numbers, right_numbers = state
    print('- ', target_number, left_numbers, right_numbers)
    calculate(target_number, left_numbers, right_numbers)
    print('=============================================')
