"""Create a compact sheet of source face crops for idle mouth inspection."""

import cv2
import numpy as np


root = '/root/LiveTalking/data/avatars/wang_ayi/face_imgs'
indices = (0, 30, 50, 75, 100, 125, 150, 200, 250, 300, 350, 401)
tiles = []
for index in indices:
    frame = cv2.imread(f'{root}/{index:08d}.png')
    cv2.putText(frame, str(index), (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 255, 255), 2)
    tiles.append(frame)
sheet = np.concatenate([np.concatenate(tiles[i:i + 4], axis=1)
                        for i in range(0, len(tiles), 4)], axis=0)
cv2.imwrite('/root/autodl-tmp/nurse-source-faces.png', sheet)
