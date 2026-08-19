import cv2
import numpy as np

from ._util import DEBUG, dump, grab, retry, tap

targets = [(907, 331, 1562, 431), # split the big digit in 8 parts
(907, 404, 1562, 504),
(907, 500, 1562, 600),
(907, 560, 1562, 660),
(907, 627, 1562, 727),
(907, 697, 1562, 809),
(907, 780, 1562, 883),
(907, 863, 1562, 975)]

scan = [(424, 360, 810, 415), # every parts on the left
(424, 360 + 76, 810, 415 + 76),
(424, 360 + 76 * 2, 810, 415 + 76 * 2),
(424, 360 + 76 * 3, 810, 415 + 76 * 3),
(424, 360 + 76 * 4, 810, 415 + 76 * 4),
(424, 360 + 76 * 5, 810, 415 + 76 * 5),
(424, 360 + 76 * 6, 810, 415 + 76 * 6),
(424, 360 + 76 * 7, 810, 415 + 76 * 7)]

ROWS = 8
# 배정된 짝의 최저 점수. 이보다 낮으면 덜 읽은 걸로 보고 다시 찍음
MIN_SCORE = 0.45


def score_matrix(bbox):
    """좌측 조각 8개 x 우측 줄 8개 매칭 점수표"""
    im = grab(bbox)

    big = []
    for target in targets:
        part = im.crop(target)
        # resize the big part and store it
        big.append(cv2.cvtColor(
            np.array(part.resize((round(part.size[0] * 0.91), round(part.size[1] * 0.91)))),
            cv2.COLOR_BGR2GRAY))

    small = [cv2.cvtColor(np.array(im.crop(box)), cv2.COLOR_BGR2GRAY) for box in scan]
    im.close()

    scores = np.zeros((ROWS, ROWS), dtype=np.float32)
    for i in range(ROWS):
        for j in range(ROWS):
            scores[i, j] = cv2.matchTemplate(big[j], small[i], cv2.TM_CCOEFF_NORMED).max()
    return scores


def assign(scores):
    """각 조각을 서로 다른 줄에 배정 (점수 높은 짝부터)

    임계값 넘는 첫 항목을 고르면 앞쪽 줄에 쏠려서 중복이 남
    높은 짝부터 확정하면 항상 순열이 나오고 오답도 줄어듦
    """
    remaining = scores.copy()
    mapping = [-1] * ROWS
    used_score = []

    for _ in range(ROWS):
        i, j = np.unravel_index(np.argmax(remaining), remaining.shape)
        mapping[i] = int(j)
        used_score.append(float(remaining[i, j]))
        remaining[i, :] = -np.inf   # 이 조각 배정 완료
        remaining[:, j] = -np.inf   # 이 줄도 사용 완료

    return mapping, min(used_score)


def read_mapping(bbox, require_score=True):
    scores = score_matrix(bbox)
    mapping, worst = assign(scores)

    print('-  배정:', ' '.join(f'{i}->{j}({scores[i, j]:.2f})' for i, j in enumerate(mapping)))
    print(f'-  최저 점수: {worst:.3f}')

    if require_score and worst < MIN_SCORE:
        return None
    return mapping


def build_moves(mapping):
    moves = []
    for i, j in enumerate(mapping):
        # 좌우 중 짧은 쪽으로 (8칸 순환)
        path = min(i - j, i - j - ROWS, i - j + ROWS, key=abs)
        if path != 0:
            key = "d" if path > 0 else "a"
            moves.extend([key] * abs(path))
        moves.append("s")
    # 마지막 's'는 첫 줄로 되감기만 해서 그대로 둠 (원본 동작 유지)
    return moves


def main(bbox):
    print('[*] Cayo Perico Fingerprint')

    if DEBUG:
        dump(bbox, 'cayo_fingerprint')

    mapping = retry(lambda: read_mapping(bbox))
    if mapping is None:
        # 점수가 계속 낮으면 확신은 없어도 최선의 배정으로 진행
        print('[!] 매칭 점수가 낮습니다. 최선의 배정으로 진행합니다.')
        dump(bbox, 'cayo_fingerprint_lowconf')
        mapping = read_mapping(bbox, require_score=False)

    moves = build_moves(mapping)

    print('-', moves)
    for key in moves:
        tap(key)

    print('[*] END')
    print('=============================================')
