import cv2
import numpy as np
from collections import deque, namedtuple

from ._util import DEBUG, dump, grab, retry, tap

tofind = (950, 155, 1335, 685)

parts = [[(482, 279, 482 + 102, 279 + 102), (0, 0)],
[(627, 279, 627 + 102, 279 + 102), (1, 0)],
[(482, 423, 482 + 102, 423 + 102), (0, 1)],
[(627, 423, 627 + 102, 423 + 102), (1, 1)],
[(482, 566, 482 + 102, 566 + 102), (0, 2)],
[(627, 566, 627 + 102, 566 + 102), (1, 2)],
[(482, 711, 482 + 102, 711 + 102), (0, 3)],
[(627, 711, 627 + 102, 711 + 102), (1, 3)]]

# 정답 조각은 항상 4개
EXPECTED_MATCHES = 4
# 4등과 5등의 점수 차. 이보다 좁으면 덜 읽은 걸로 보고 다시 찍음
MIN_MARGIN = 0.06


def match_score(img, subimg):
    """'subimg'가 'img' 안에 얼마나 맞는지, 최고 점수"""
    subimg1 = cv2.cvtColor(np.array(subimg), cv2.COLOR_BGR2GRAY) # need gray image to do the matchTemplate
    res = cv2.matchTemplate(img, subimg1, cv2.TM_CCOEFF_NORMED)
    return float(res.max())


def read_targets(bbox, require_margin=True):
    """맞는 지문 조각 4개의 좌표

    고정 임계값으로 자르지 않고 8개 점수를 매겨 상위 4개를 고름
    정답이 항상 4개라는 규칙을 쓰니 화면 밝기나 스케일에 안 흔들림
    """
    im = grab(bbox)
    sub0_ = im.crop(tofind)
    # need to resize the image because fingerprints parts is smaller than the
    # image + need gray image to do the matchTemplate
    sub0 = cv2.cvtColor(
        np.array(sub0_.resize((round(sub0_.size[0] * 0.77), round(sub0_.size[1] * 0.77)))),
        cv2.COLOR_BGR2GRAY)

    scores = [match_score(sub0, im.crop(part[0])) for part in parts]
    sub0_.close()
    im.close()

    order = sorted(range(len(parts)), key=lambda i: scores[i], reverse=True)
    margin = scores[order[EXPECTED_MATCHES - 1]] - scores[order[EXPECTED_MATCHES]]

    print('-  점수:', ' '.join(f'{parts[i][1]}={scores[i]:.3f}' for i in order))
    print(f'-  4등/5등 격차: {margin:.3f}')

    if require_margin and margin < MIN_MARGIN:
        return None
    return [parts[i][1] for i in order[:EXPECTED_MATCHES]]


def find_shortest_solution(target_coordinates):
    Point = namedtuple('Point', ('x', 'y'))
    ReverseLinkedNode = namedtuple("ReverseLinkedNode", ('value', 'prev_node', 'idx'))
    rows, cols = 4, 2
    directions = [(0, 1, 's'), (1, 0, 'd'), (0, -1, 'w'), (-1, 0, 'a')]  # (delta_x, delta_y, key)

    target_coordinates = [p if isinstance(p, Point) else Point(*p) for p in target_coordinates]
    target_mask = 0
    for target in target_coordinates:
        target_mask |= 1 << ((target.y * cols) + target.x)

    # BFS initialization
    current_pos = Point(0, 0)
    visited_mask = 1
    path_head: ReverseLinkedNode = ReverseLinkedNode(None, None, -1)
    if current_pos in target_coordinates:
        path_head = ReverseLinkedNode('return', path_head, 0)
    queue = deque([(current_pos, visited_mask, path_head)])  # (current_position, visited_mask, path_head)

    # loop until all points have been visited or a solution has been found
    while len(queue) > 0:
        current_pos, visited_mask, path_head = queue.popleft()

        # if all target points are visited, return the final path
        if visited_mask & target_mask == target_mask:
            output_list = [None] * (path_head.idx + 1)
            while path_head.idx >= 0:
                output_list[path_head.idx] = path_head.value
                path_head = path_head.prev_node
            return output_list + ['tab']

        # explore neighbors
        for delta_x, delta_y, key in directions:
            new_x, new_y = current_pos.x + delta_x, current_pos.y + delta_y
            # correct for wrapping
            if new_x == -1:
                new_x, new_y = cols-1, new_y-1
            elif new_x == cols:
                new_x, new_y = 0, new_y+1
            new_y = new_y % rows

            next_pos = Point(new_x, new_y)
            pos_mask = 1 << ((next_pos.y * cols) + next_pos.x)
            next_visited_mask = visited_mask | pos_mask
            # skip if visited
            if visited_mask == next_visited_mask:
                continue

            next_path_head = ReverseLinkedNode(key, path_head, path_head.idx+1)
            # if next_pos is a target point
            if target_mask & pos_mask != 0:
                next_path_head = ReverseLinkedNode('return', next_path_head, next_path_head.idx+1)
            queue.append((next_pos, next_visited_mask, next_path_head))

    raise Exception('No solution found')


def main(bbox):
    print('[*] Casino Fingerprint')

    if DEBUG:
        dump(bbox, 'casino_fingerprint')

    togo = retry(lambda: read_targets(bbox))
    if togo is None:
        # 격차가 계속 좁으면 확신은 없어도 제일 좋은 4개로 진행
        print('[!] 점수 격차가 좁습니다. 상위 4개로 진행합니다.')
        dump(bbox, 'casino_fingerprint_lowconf')
        togo = read_targets(bbox, require_margin=False)

    moves = find_shortest_solution(togo)

    print('-', moves)
    for key in moves:
        tap(key)
    print('[*] END')
    print('=============================================')
