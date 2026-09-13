"""BruteForce Matcher - Hingdragon417/Lester-Ver3.0 에서 이식

움직이는 표적이 판정선을 지나는 순간에 맞춰 눌러야 한다
그래서 키 입력은 tap 이 아니라 press_instant 를 쓴다
tap 은 설정된 간격과 SLOW 배율을 적용하는데 여기선 그게 그대로 빗나감이 된다
"""

import time

import cv2
import numpy as np

from ._util import DEBUG, _env, dump, grab, press_instant

WATCH_TIMEOUT = _env('LESTER_BRUTE_TIMEOUT', 60)
PRESS_COOLDOWN = 0.45
RED_THRESHOLD = 20
BAR_CENTER_MARGIN = 13
MOVEMENT_THRESHOLD = 180
PRESS_LEAD_SECONDS = 0.055

# 1920x1080 coordinates from the BruteForce screen.
COLUMN_CENTERS = [594, 690, 786, 883, 979, 1075, 1172, 1268]
COLUMN_WIDTH = 90
COLUMN_Y = (250, 875)
MOVEMENT_Y = (380, 820)
BLUE_BAR_BOX = (250, 585, 1460, 650)

def column_box(index):
    center = COLUMN_CENTERS[index]
    return (
        center - COLUMN_WIDTH // 2,
        COLUMN_Y[0],
        center + COLUMN_WIDTH // 2,
        COLUMN_Y[1]
    )

def hit_box(index):
    col = column_box(index)
    return (
        max(col[0], BLUE_BAR_BOX[0]),
        max(col[1], BLUE_BAR_BOX[1]),
        min(col[2], BLUE_BAR_BOX[2]),
        min(col[3], BLUE_BAR_BOX[3])
    )

def movement_box(index):
    col = column_box(index)
    return (col[0], MOVEMENT_Y[0], col[2], MOVEMENT_Y[1])

def red_mask(im):
    hsv = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2HSV)
    lower_1 = np.array([0, 90, 90])
    upper_1 = np.array([12, 255, 255])
    lower_2 = np.array([168, 90, 90])
    upper_2 = np.array([179, 255, 255])

    return cv2.bitwise_or(
        cv2.inRange(hsv, lower_1, upper_1),
        cv2.inRange(hsv, lower_2, upper_2)
    )

def column_frame(im, index):
    crop = im.crop(movement_box(index))
    gray = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2GRAY)
    return cv2.GaussianBlur(gray, (5, 5), 0)

def detect_active_column(im, previous_frames):
    scores = []

    for index in range(len(COLUMN_CENTERS)):
        frame = column_frame(im, index)
        previous = previous_frames[index]
        if previous is None:
            score = 0
        else:
            diff = cv2.absdiff(frame, previous)
            score = int(np.count_nonzero(diff > 18))

        previous_frames[index] = frame
        scores.append(score)

    moving_columns = [index for index, score in enumerate(scores) if score >= MOVEMENT_THRESHOLD]
    if not moving_columns:
        return None, scores

    return moving_columns[0], scores

def red_in_hit_zone(im, index):
    box = column_box(index)
    crop = im.crop(box)
    mask = red_mask(crop)
    component_count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    bar_center_y = (BLUE_BAR_BOX[1] + BLUE_BAR_BOX[3]) / 2

    candidates = []
    for component in range(1, component_count):
        pixels = int(stats[component, cv2.CC_STAT_AREA])
        if pixels >= RED_THRESHOLD:
            x = box[0] + float(centroids[component][0])
            y = box[1] + float(centroids[component][1])
            left = box[0] + int(stats[component, cv2.CC_STAT_LEFT])
            top = box[1] + int(stats[component, cv2.CC_STAT_TOP])
            width = int(stats[component, cv2.CC_STAT_WIDTH])
            height = int(stats[component, cv2.CC_STAT_HEIGHT])
            candidates.append({
                'pixels': pixels,
                'center_x': x,
                'center_y': y,
                'distance_to_bar': abs(y - bar_center_y),
                'box': (left, top, left + width, top + height)
            })

    if not candidates:
        return 0, None, None, None, None

    candidate = min(candidates, key=lambda item: item['distance_to_bar'])
    return (
        candidate['pixels'],
        candidate['center_y'],
        candidate['center_x'],
        candidate['distance_to_bar'],
        candidate['box']
    )

def should_press_letter(red_center_y, previous_y, previous_time, now, already_pressed):
    if red_center_y is None or already_pressed:
        return False, False, False, target_y(), None, None

    target = target_y()
    if previous_y is None or previous_time is None:
        moving_down = True
        first_frame_on_target = abs(red_center_y - target) <= BAR_CENTER_MARGIN
        return first_frame_on_target, moving_down, False, target, None, None

    elapsed = max(now - previous_time, 0.001)
    velocity = (red_center_y - previous_y) / elapsed
    moving_down = velocity > 20
    crossed_trigger = previous_y < target <= red_center_y
    if moving_down:
        time_to_trigger = (target - red_center_y) / velocity
    else:
        time_to_trigger = None

    predicted_hit = time_to_trigger is not None and 0 <= time_to_trigger <= PRESS_LEAD_SECONDS
    return moving_down and (crossed_trigger or predicted_hit), moving_down, crossed_trigger, target, velocity, time_to_trigger

def target_y():
    return (BLUE_BAR_BOX[1] + BLUE_BAR_BOX[3]) / 2

def main(bbox):
    print('[*] BruteForce Matcher')

    if DEBUG:
        dump(bbox, 'bruteforce')

    started_at = time.time()
    last_press_at = 0
    was_on_bar = False
    press_count = 0
    previous_frames = [None for _ in COLUMN_CENTERS]
    last_active_column = None
    previous_y = None
    previous_time = None
    pressed_active_column = None

    while time.time() - started_at < WATCH_TIMEOUT:
        im = grab(bbox)
        active_column, _ = detect_active_column(im, previous_frames)
        if active_column is None:
            time.sleep(0.02)
            continue

        if active_column != last_active_column:
            was_on_bar = False
            previous_y = None
            previous_time = None
            pressed_active_column = None
            last_active_column = active_column

        red_pixels, red_center_y, red_center_x, distance_to_bar, active_box = red_in_hit_zone(im, active_column)
        now = time.time()
        should_press, moving_down, crossed_trigger, target_line_y, velocity, time_to_trigger = should_press_letter(
            red_center_y,
            previous_y,
            previous_time,
            now,
            pressed_active_column == active_column
        )

        if should_press and not was_on_bar and now - last_press_at >= PRESS_COOLDOWN:
            velocity_text = 'n/a' if velocity is None else f'{velocity:.1f}'
            print(f'[*] Column {active_column + 1}: {red_pixels}px y={red_center_y:.1f} target={target_line_y:.1f} velocity={velocity_text} -> enter')
            press_instant('enter')
            last_press_at = now
            press_count += 1
            pressed_active_column = active_column
            was_on_bar = True
            time.sleep(0.12)
            continue

        previous_y = red_center_y
        previous_time = now
        was_on_bar = should_press
        time.sleep(0.02)

    print(f'[*] END ({press_count} hits)')
    print('=============================================')
