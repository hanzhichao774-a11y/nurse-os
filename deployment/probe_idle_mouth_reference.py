"""Compare Wav2Lip silent output with a closed-mouth source reference."""

import cv2
import numpy as np
import torch

from avatars.wav2lip import audio
from avatars.wav2lip_avatar import load_model


root = '/root/LiveTalking/data/avatars/wang_ayi/face_imgs'
reference = cv2.imread(f'{root}/00000030.png')
indices = (30, 75, 125, 150, 200, 250, 300, 350)
model = load_model('/root/LiveTalking/models/wav2lip.pth')
device = next(model.parameters()).device
silence = audio.melspectrogram(np.zeros(16000, dtype=np.float32))[:, :16]
mel = torch.FloatTensor(silence[None, None]).to(device)

mask = np.zeros((256, 256), dtype=np.float32)
cv2.ellipse(mask, (145, 190), (65, 34), 0, 0, 360, 1, -1)
mask = cv2.GaussianBlur(mask, (31, 31), 10)[..., None]


def predict(frame):
    masked = frame.copy()
    masked[128:] = 0
    image = np.concatenate((masked, frame), axis=2) / 255.0
    image = torch.FloatTensor(image.transpose(2, 0, 1)[None]).to(device)
    with torch.no_grad():
        result = model(mel, image)[0].cpu().numpy().transpose(1, 2, 0)
    return np.uint8(np.clip(result * 255, 0, 255))


rows = []
for index in indices:
    face = cv2.imread(f'{root}/{index:08d}.png')
    altered = np.uint8(np.clip(face * (1 - mask) + reference * mask, 0, 255))
    original_pred = predict(face)
    altered_pred = predict(altered)
    labeled = []
    for image, label in ((face, f'{index} source'),
                         (original_pred, 'silent original'),
                         (altered_pred, 'silent reference')):
        image = np.ascontiguousarray(image)
        cv2.putText(image, label, (4, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                    (0, 255, 255), 1)
        labeled.append(image)
    rows.append(np.concatenate(labeled, axis=1))
sheet = np.concatenate(rows, axis=0)
cv2.imwrite('/root/autodl-tmp/nurse-idle-mouth-comparison.png', sheet)
