"""Host Number Matcher - Hingdragon417/Lester-Ver3.0 에서 이식

원본은 ImageGrab 을 직접 부르고 고정 지연을 썼다
캡처는 _util.grab (종횡비 보정 + 1920x1080 정규화), 키는 tap (포커스 확인 +
설정 반영) 으로 바꿨다
"""

import time

import cv2
import numpy as np

from ._util import DEBUG, _env, dump, grab, tap

ROWS = 8
COLS = 10

# 1920x1080 coordinates from the "CONNECTING TO THE HOST" number grid.
GRID_X = [521, 615, 711, 806, 900, 995, 1090, 1185, 1279, 1374]
GRID_Y = [431, 492, 553, 614, 675, 736, 797, 858]

# Four red target number pairs at the top: 20.17.09.85
TARGET_BOXES = [
    (764, 230, 850, 296),
    (858, 230, 944, 296),
    (953, 230, 1039, 296),
    (1047, 230, 1133, 296),
]

CELL_SIZE = (92, 58)
TARGET_SIZE = (92, 58)
DIGIT_SIZE = (42, 58)
MATCH_THRESHOLD = 0.28
TARGET_PIXEL_THRESHOLD = 80
SELECTED_PIXEL_THRESHOLD = 250
WATCH_TIMEOUT = _env('LESTER_HOST_TIMEOUT', 30)
MOVE_TIMEOUT = _env('LESTER_HOST_MOVE_TIMEOUT', 15)
MOVE_KEYS = {
    'up': 'w',
    'down': 's',
    'left': 'a',
    'right': 'd'
}

def red_mask(im):
    hsv = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2HSV)
    lower_1 = np.array([0, 80, 80])
    upper_1 = np.array([12, 255, 255])
    lower_2 = np.array([168, 80, 80])
    upper_2 = np.array([179, 255, 255])

    return cv2.bitwise_or(
        cv2.inRange(hsv, lower_1, upper_1),
        cv2.inRange(hsv, lower_2, upper_2)
    )

def bright_mask(im):
    hsv = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2HSV)
    lower = np.array([0, 0, 135])
    upper = np.array([179, 90, 255])
    return cv2.inRange(hsv, lower, upper)

def number_mask(im):
    return cv2.bitwise_or(bright_mask(im), red_mask(im))

def normalize(mask, size):
    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or len(ys) == 0:
        return np.zeros(size[::-1], dtype=np.uint8)

    x1, x2 = max(0, xs.min() - 4), min(mask.shape[1], xs.max() + 5)
    y1, y2 = max(0, ys.min() - 4), min(mask.shape[0], ys.max() + 5)
    cropped = mask[y1:y2, x1:x2]
    return cv2.resize(cropped, size, interpolation=cv2.INTER_AREA)

def split_digits(mask):
    columns = np.count_nonzero(mask, axis=0)
    groups = []
    start = None

    for i, count in enumerate(columns):
        if count > 0 and start is None:
            start = i
        elif count == 0 and start is not None:
            groups.append((start, i))
            start = None

    if start is not None:
        groups.append((start, len(columns)))

    groups = [(start, end) for start, end in groups if end - start >= 3]
    if len(groups) < 2:
        return None

    if len(groups) > 2:
        groups.sort(key=lambda group: group[1] - group[0], reverse=True)
        groups = sorted(groups[:2])

    digits = []
    for start, end in groups:
        digit = mask[:, max(0, start - 2):min(mask.shape[1], end + 2)]
        digits.append(normalize(digit, DIGIT_SIZE))

    return digits

def target_templates(im):
    templates = []
    target_counts = []

    for index, box in enumerate(TARGET_BOXES):
        crop = im.crop(box)
        mask = red_mask(crop)
        pixels = int(np.count_nonzero(mask))
        target_counts.append((index, box, pixels))

        if pixels < TARGET_PIXEL_THRESHOLD:
            templates.append(None)
        else:
            templates.append(split_digits(mask))

    return templates, target_counts

def cell_template(im, col, row):
    x = GRID_X[col]
    y = GRID_Y[row]
    crop = im.crop((x - CELL_SIZE[0] // 2, y - CELL_SIZE[1] // 2, x + CELL_SIZE[0] // 2, y + CELL_SIZE[1] // 2))
    return split_digits(number_mask(crop))

def image_match_score(target, cell):
    target = target > 0
    cell = cell > 0
    best = 0

    for dy in range(-3, 4):
        for dx in range(-3, 4):
            shifted = np.zeros_like(cell)

            source_y1 = max(0, -dy)
            source_y2 = min(cell.shape[0], cell.shape[0] - dy)
            source_x1 = max(0, -dx)
            source_x2 = min(cell.shape[1], cell.shape[1] - dx)

            dest_y1 = max(0, dy)
            dest_y2 = min(cell.shape[0], cell.shape[0] + dy)
            dest_x1 = max(0, dx)
            dest_x2 = min(cell.shape[1], cell.shape[1] + dx)

            shifted[dest_y1:dest_y2, dest_x1:dest_x2] = cell[source_y1:source_y2, source_x1:source_x2]
            intersection = np.count_nonzero(target & shifted)
            union = np.count_nonzero(target | shifted)
            if union:
                best = max(best, intersection / union)

    return float(best)

def match_score(target, cell):
    if target is None or cell is None or len(target) != 2 or len(cell) != 2:
        return 0

    return (image_match_score(target[0], cell[0]) + image_match_score(target[1], cell[1])) / 2

def find_current_selector(im):
    selected_cells = []

    for row in range(ROWS):
        for col in range(COLS):
            x = GRID_X[col]
            y = GRID_Y[row]
            crop = im.crop((x - CELL_SIZE[0] // 2, y - CELL_SIZE[1] // 2, x + CELL_SIZE[0] // 2, y + CELL_SIZE[1] // 2))
            red_pixels = int(np.count_nonzero(red_mask(crop)))

            if red_pixels >= SELECTED_PIXEL_THRESHOLD:
                selected_cells.append((col, row, red_pixels))

    if len(selected_cells) == 0:
        return (0, 0), selected_cells

    selected_cells.sort(key=lambda cell: (cell[1], cell[0]))
    return (selected_cells[0][0], selected_cells[0][1]), selected_cells

def find_matching_sequence(im):
    targets, target_counts = target_templates(im)
    if any(target is None for target in targets):
        raise ValueError('Top target sequence not detected')

    cell_templates = {}
    for row in range(ROWS):
        for col in range(COLS):
            cell_templates[(col, row)] = cell_template(im, col, row)

    scores = []
    total_cells = ROWS * COLS
    for start_index in range(total_cells):
        total = 0
        segment_scores = []
        sequence_cells = []

        for offset, target in enumerate(targets):
            cell_index = (start_index + offset) % total_cells
            row = cell_index // COLS
            col = cell_index % COLS
            score = match_score(target, cell_templates[(col, row)])
            total += score
            segment_scores.append(score)
            sequence_cells.append((col, row))

        start_row = start_index // COLS
        start_col = start_index % COLS
        scores.append((total / 4, start_col, start_row, segment_scores, sequence_cells))

    scores.sort(reverse=True, key=lambda score: score[0])
    best_score, col, row, _, sequence_cells = scores[0]
    selector_position, selected_cells = find_current_selector(im)

    if best_score < MATCH_THRESHOLD:
        raise ValueError(f'No matching grid sequence found. best={best_score:.3f} at {(col, row)}')

    return col, row, best_score, selector_position, targets

def has_host_screen(im):
    targets, _ = target_templates(im)
    target_ok = sum(1 for target in targets if target is not None) == 4

    grid_cells = 0
    for row in range(ROWS):
        for col in range(COLS):
            x = GRID_X[col]
            y = GRID_Y[row]
            crop = im.crop((x - CELL_SIZE[0] // 2, y - CELL_SIZE[1] // 2, x + CELL_SIZE[0] // 2, y + CELL_SIZE[1] // 2))
            if np.count_nonzero(number_mask(crop)) > 80:
                grid_cells += 1

    return target_ok and grid_cells >= 50

def wait_for_host_screen(bbox):
    print('[*] Waiting for Host Number screen...')
    started_at = time.time()

    while time.time() - started_at < WATCH_TIMEOUT:
        im = grab(bbox)
        if has_host_screen(im):
            print('[*] Host Number screen detected.')
            return im

        time.sleep(0.05)

    im = grab(bbox)
    raise ValueError('Timed out waiting for Host Number screen')

def selector_distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def next_move(current_position, target_position):
    current_col, current_row = current_position
    target_col, target_row = target_position

    if current_row < target_row:
        return 'down'
    if current_row > target_row:
        return 'up'

    if current_col < target_col:
        return 'right'
    if current_col > target_col:
        return 'left'

    return None

def press_move_key(key):
    tap(MOVE_KEYS.get(key, key))

def move_to_sequence(bbox, target_col, target_row, current_position):
    print('[*] Moving red selector to target sequence...')
    target_position = (target_col, target_row)
    started_at = time.time()

    while time.time() - started_at < MOVE_TIMEOUT:
        im = grab(bbox)
        try:
            target_col, target_row, score, current_position, targets = find_matching_sequence(im)
            target_position = (target_col, target_row)
            print(f'[*] Live target at {target_position}, selector={current_position}, score={score:.3f}')
        except ValueError:
            current_position, selected_cells = find_current_selector(im)

        if current_position == target_position:
            print(f'[*] Selector reached target at col={target_col + 1}, row={target_row + 1}')
            tap('enter')
            return

        key = next_move(current_position, target_position)
        if key is None:
            tap('enter')
            return

        print(f'[*] Selector at {current_position}; pressing {key}')
        press_move_key(key)

    raise ValueError(f'Timed out moving selector to {(target_col, target_row)}')

def selected_sequence_score(im, target_col, target_row, targets):
    scores = []
    start_index = (target_row * COLS) + target_col
    total_cells = ROWS * COLS

    for offset, target in enumerate(targets):
        cell_index = (start_index + offset) % total_cells
        row = cell_index // COLS
        col = cell_index % COLS
        scores.append(match_score(target, cell_template(im, col, row)))

    return sum(scores) / len(scores), scores

def wait_for_selected_sequence(bbox, target_col, target_row, targets):
    print('[*] Waiting for selected digits to match target...')
    started_at = time.time()

    while time.time() - started_at < WATCH_TIMEOUT:
        im = grab(bbox)
        score, scores = selected_sequence_score(im, target_col, target_row, targets)

        if score >= MATCH_THRESHOLD and min(scores) >= 0.20:
            print(f'[*] Selected digits matched: {score:.3f} {scores}')
            tap('enter')
            return

        time.sleep(0.05)

    raise ValueError('Timed out waiting for selected digits to match target')

def main(bbox):
    print('[*] Host Number Matcher')

    if DEBUG:
        dump(bbox, 'host_number')

    try:
        im = wait_for_host_screen(bbox)
        col, row, score, current_position, targets = find_matching_sequence(im)
        print(f'[*] Target sequence found at col={col + 1}, row={row + 1}, score={score:.3f}')
        print(f'[*] Current selector starts at col={current_position[0] + 1}, row={current_position[1] + 1}')
        move_to_sequence(bbox, col, row, current_position)
        print('[*] END')
    except ValueError as e:
        print(f'[!] {e}')
        dump(bbox, 'host_number_fail')
    finally:
        print('=============================================')
