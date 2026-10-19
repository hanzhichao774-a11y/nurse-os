import asyncio
import time

import av
import edge_tts


TEXT = '哎，护士啊，我这脚麻得厉害，凉飕飕的，眼睛也看不清。你说这糖尿病，是不是要出大事了？'


async def main():
    start = time.monotonic()
    decoder = av.CodecContext.create('mp3', 'r')
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
    total_pcm = 0

    def decode(data):
        nonlocal total_pcm
        packets = decoder.parse(data)
        for packet in packets:
            for frame in decoder.decode(packet):
                for result in resampler.resample(frame):
                    if total_pcm == 0:
                        print('first_pcm_sec', round(time.monotonic()-start, 3), flush=True)
                    total_pcm += result.to_ndarray().nbytes
    total_mp3 = 0
    async for part in edge_tts.Communicate(TEXT, 'zh-CN-XiaoyiNeural', rate='-5%', pitch='-8Hz').stream():
        if part['type'] == 'audio':
            if total_mp3 == 0:
                print('first_mp3_sec', round(time.monotonic()-start, 3), flush=True)
            decode(part['data'])
            total_mp3 += len(part['data'])
    decode(b'')
    for frame in decoder.decode(None):
        for result in resampler.resample(frame):
            total_pcm += result.to_ndarray().nbytes
    print('total_sec', round(time.monotonic()-start, 3), 'mp3', total_mp3, 'pcm', total_pcm, flush=True)


asyncio.run(main())
