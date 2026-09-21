#!/usr/bin/env python3
"""Exercise the same JSON and multipart image requests LibreChat sends.

Requires Pillow. Writes generated images and timing results to --output-dir.
"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import time
import urllib.request
import uuid

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080/v1')
    parser.add_argument('--output-dir', type=Path, default=Path('/tmp/qwen-image-check'))
    parser.add_argument('--require-transparency', action='store_true',
                        help='Also require substantial transparency in both images (currently experimental)')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def request(endpoint, body, content_type, filename):
        req = urllib.request.Request(
            args.base_url.rstrip('/') + endpoint,
            data=body,
            headers={
                'Content-Type': content_type,
                'Authorization': 'Bearer ' + os.environ.get('QWEN_IMAGE_API_KEY', 'vllm'),
            },
        )
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=900) as response:
            payload = json.load(response)
        data = base64.b64decode(payload['data'][0]['b64_json'], validate=True)
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            assert image.size == (1024, 1024), image.size
            assert image.format == 'PNG', image.format
            assert image.mode == 'RGBA', image.mode
            sample = image.resize((256, 256), Image.Resampling.NEAREST)
            pixels = list(sample.get_flattened_data() if hasattr(sample, 'get_flattened_data') else sample.getdata())
            result = {
                'file': filename, 'seconds': round(time.monotonic() - start, 2),
                'size': list(image.size), 'mode': image.mode,
                'alpha_extrema': list(image.getchannel('A').getextrema()),
                'transparent_fraction': round(sum(a < 32 for r, g, b, a in pixels) / len(pixels), 3),
                'red_pixels': sum(a > 200 and r > 80 and r > 1.3 * g and r > 1.3 * b for r, g, b, a in pixels),
                'blue_pixels': sum(a > 200 and b > 80 and b > 1.3 * g and b > 1.3 * r for r, g, b, a in pixels),
            }
        (args.output_dir / filename).write_bytes(data)
        results.append(result)
        print(json.dumps(result), flush=True)
        return data

    original = request('/images/generations', json.dumps({
        'model': 'qwen-image-2.1',
        'prompt': 'This is an RGBA image with transparency. A cute red ceramic robot '
                  'holding a white sign that clearly reads HELLO. Clean polished '
                  '3D sticker illustration, centered, full body. The image has '
                  'alpha channel and the background is transparent.',
        'size': '1024x1024', 'n': 1, 'quality': 'auto',
        'background': 'transparent', 'output_format': 'png',
    }).encode(), 'application/json', 'generated.png')
    assert results[-1]['red_pixels'] > 1.5 * results[-1]['blue_pixels'], 'Expected a red robot'

    boundary = 'qwen-image-check-' + uuid.uuid4().hex
    body = bytearray()
    fields = {
        'model': 'qwen-image-2.1', 'size': '1024x1024', 'quality': 'auto',
        'prompt': 'Change the red robot to blue. Keep the same robot, composition, '
                  'white HELLO sign and transparent background. '
                  'This is an RGBA image with transparency and an alpha channel.',
    }
    for name, value in fields.items():
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="generated.png"\r\nContent-Type: image/png\r\n\r\n'.encode())
    body.extend(original)
    body.extend(f'\r\n--{boundary}--\r\n'.encode())
    edited = request('/images/edits', bytes(body), f'multipart/form-data; boundary={boundary}', 'edited.png')
    assert edited != original, 'Editing returned an identical file'
    assert results[-1]['blue_pixels'] > 1.5 * results[-1]['red_pixels'], 'Expected the edit to turn the robot blue'
    (args.output_dir / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    transparent = all(result['transparent_fraction'] > 0.25 for result in results)
    if not transparent:
        print('NOTE: substantial transparency was not preserved in both images; clean cutouts remain experimental.', flush=True)
    if args.require_transparency:
        assert transparent, 'Expected substantial transparent area in both images'


if __name__ == '__main__':
    main()
