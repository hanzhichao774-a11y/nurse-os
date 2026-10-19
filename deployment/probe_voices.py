import asyncio
import edge_tts
from pathlib import Path


async def main():
    cases = [
        ('zh-CN-XiaoxiaoNeural', {}),
        ('zh-CN-XiaoxiaoNeural', {'rate': '-5%', 'pitch': '-8Hz'}),
        ('zh-CN-XiaoyiNeural', {}),
        ('zh-CN-XiaoyiNeural', {'rate': '-5%', 'pitch': '-8Hz'}),
    ]
    for voice, options in cases:
        try:
            communicate = edge_tts.Communicate('哎，我这脚麻了一个月了。', voice, **options)
            data = bytearray()
            async for part in communicate.stream():
                if part['type'] == 'audio':
                    data.extend(part['data'])
            sample = Path('/root/demo_backend') / f'voice_sample_{voice}_{"adjusted" if options else "default"}.mp3'
            sample.write_bytes(data)
            print(voice, options, len(data), flush=True)
        except Exception as exc:
            print(voice, options, type(exc).__name__, str(exc)[:120], flush=True)


asyncio.run(main())
