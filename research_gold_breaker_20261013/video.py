"""Retrieve public source clip for frame inspection; never print signed URLs."""
import json
from pathlib import Path
import re
import requests

HERE=Path(__file__).resolve().parent


def main():
    folder=HERE/'media';folder.mkdir(exist_ok=True)
    file=folder/'source.mp4'
    if file.exists():print('Public video already cached.');return
    session=requests.Session()
    session.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.tiktok.com/'})
    response=session.get('https://www.tiktok.com/@_crypto_hustler_/video/7597429143780871432',timeout=20)
    response.raise_for_status()
    match=re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',response.text)
    if not match:raise ValueError('Video metadata unavailable')
    item=json.loads(match.group(1))['__DEFAULT_SCOPE__']['webapp.video-detail']['itemInfo']['itemStruct']
    video=None
    for field in ('downloadAddr','playAddr'):
        address=item['video'].get(field)
        if not isinstance(address,str) or not address.startswith('https://'):continue
        response=session.get(address,timeout=30)
        if response.status_code==200 and response.headers.get('Content-Type','').startswith('video/') and len(response.content)<80_000_000:
            video=response;break
    if video is None:raise ValueError('Public video download unavailable')
    file.write_bytes(video.content)
    print('Public video cached for inspection; bytes='+str(len(video.content)))


if __name__=='__main__':
    try:main()
    except Exception as error:print('Video inspection stopped: '+type(error).__name__);raise SystemExit(1)
