"""Render one silent Wav2Lip frame to compare against the source mouth."""

import cv2
import numpy as np
import torch

from avatars.wav2lip import audio
from avatars.wav2lip_avatar import load_avatar, load_model, device


full, faces, boxes = load_avatar('wang_ayi')
index = 0
face = faces[index]
masked = face.copy()
masked[face.shape[0] // 2:] = 0
image = np.concatenate((masked, face), axis=2) / 255.0
mel = audio.melspectrogram(np.zeros(16000, dtype=np.float32))[:, :16]
image_tensor = torch.FloatTensor(np.transpose(image, (2, 0, 1))[None]).to(device)
mel_tensor = torch.FloatTensor(mel[None, None]).to(device)
model = load_model('/root/LiveTalking/models/wav2lip.pth')
with torch.no_grad():
    prediction = model(mel_tensor, image_tensor)[0].cpu().numpy().transpose(1, 2, 0) * 255
y1, y2, x1, x2 = boxes[index]
result = full[index].copy()
result[y1:y2, x1:x2] = cv2.resize(prediction.astype(np.uint8), (x2 - x1, y2 - y1))
cv2.imwrite('/root/demo_backend/silent_source.png', full[index])
cv2.imwrite('/root/demo_backend/silent_generated.png', result)
print('bbox', boxes[index], 'face', face.shape, 'source', full[index].shape)
