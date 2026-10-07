"""Resumable full-precision Fish S2 Pro audiobook rendering."""
import argparse
import contextlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from audiobook import GPU, STATE, digest, read_json, write_json


def load_engine(reference, *, compile_decode=True):
    os.environ['CUDA_VISIBLE_DEVICES'] = GPU
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    sys.path.insert(0, str(STATE / 'vendor/fish-speech'))
    import torch
    from accelerate import init_empty_weights
    from fish_speech.models.text2semantic.inference import (
        decode_one_token_ar,
        encode_audio,
        load_codec_model,
    )
    from fish_speech.models.text2semantic.llama import (
        DualARTransformer,
        _remap_fish_qwen3_omni_keys,
    )
    from safetensors.torch import load_file
    torch.set_num_threads(4)
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError('Select exactly one available CUDA GPU with CUDA_VISIBLE_DEVICES')
    free, total = torch.cuda.mem_get_info()
    if free < 24 * 1024**3:
        raise RuntimeError('Need at least 24 GiB free for Fish rendering')
    torch.cuda.set_per_process_memory_fraction(min(26 * 1024**3 / total, 1.0))
    path = STATE / 'models/Fish-S2-Pro'
    # Keep numerical buffers materialized; checkpoint assignment fills parameters.
    with init_empty_weights(include_buffers=False):
        model = DualARTransformer.from_pretrained(path, load_weights=False, max_length=4096)
    # Assign outside init_empty_weights so its registration hook cannot remap the
    # loaded tensors back to meta. Use the same key conversion as upstream.
    index = read_json(path / 'model.safetensors.index.json')
    weights = {}
    for shard in sorted(set(index['weight_map'].values())):
        weights.update(load_file(str(path / shard), device='cpu'))
    model.load_state_dict(_remap_fish_qwen3_omni_keys(weights), strict=True, assign=True)
    del weights
    model = model.to(device='cuda', dtype=torch.bfloat16).eval()
    model._cache_setup_done = False
    codec = load_codec_model(path / 'codec.pth', 'cuda', precision=torch.float32)
    reference_codes = encode_audio(reference, codec, 'cuda').cpu() if reference else None
    decode = decode_one_token_ar
    if compile_decode:
        decode = torch.compile(decode, backend='inductor', mode='default',
                               fullgraph=True, dynamic=True)
    print(json.dumps({'event': 'model_loaded', 'device': torch.cuda.get_device_name(),
                      'sample_rate': codec.sample_rate, 'compiled_decode': compile_decode,
                      'allocated_GiB': torch.cuda.memory_allocated()/1024**3}), flush=True)
    return model, codec, decode, reference_codes


def synthesize(engine, text, reference_text, path, seed, *, compiled_decode=True):
    import numpy as np
    import soundfile as sf
    import torch
    from fish_speech.models.text2semantic.inference import (
        decode_to_audio,
        generate_long,
    )
    model, codec, decode, reference_codes = engine
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    started = time.monotonic()
    codes = []
    # The upstream prompt visualizer is verbose; the plan already preserves the text.
    with torch.inference_mode(), open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink):
        for response in generate_long(model=model, device='cuda', decode_one_token=decode,
                text=text, max_new_tokens=1600, top_p=0.9, top_k=30, temperature=1.0,
                prompt_text=[reference_text] if reference_codes is not None else None,
                prompt_tokens=[reference_codes] if reference_codes is not None else None,
                chunk_length=2048, compile=compiled_decode):
            if response.action == 'sample':
                codes.append(response.codes)
        merged = torch.cat(codes, dim=1)
        if merged.shape[1] >= 1598:
            raise RuntimeError('Generation reached token limit')
        audio = decode_to_audio(merged.to('cuda'), codec).cpu().float().numpy()
    duration = len(audio)/codec.sample_rate
    wpm = len(text.split())/duration*60
    if not len(audio) or not np.isfinite(audio).all():
        raise RuntimeError('Invalid generated audio')
    if len(text.split()) > 15 and not 65 < wpm < 260:
        raise RuntimeError(f'Implausible speaking rate: {wpm:.1f}')
    peak = float(np.abs(audio).max())
    if peak > 0.999:
        audio *= 0.98/peak
    tmp = path.with_suffix('.tmp.wav')
    sf.write(tmp, audio, codec.sample_rate, subtype='PCM_24')
    tmp.replace(path)
    return {'seconds': duration, 'sample_rate': codec.sample_rate, 'frames': len(audio),
            'seed': seed, 'words_per_minute': wpm, 'generation_seconds': time.monotonic()-started,
            'peak_before_scaling': peak, 'sha256': digest(path.read_bytes()),
            'peak_allocated_GiB': torch.cuda.max_memory_allocated()/1024**3}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--stop', type=int)
    parser.add_argument('--blocks', type=int, nargs='+', help='Render only these block IDs')
    parser.add_argument('--seed', type=int, default=1000)
    parser.add_argument('--retry', action='store_true')
    args = parser.parse_args()
    job = args.job.resolve()
    plan, narrator = read_json(job / 'plan.json'), read_json(job / 'narrator.json')
    if plan['model'] != 'fishaudio/s2-pro':
        raise ValueError('This job was not prepared for Fish')
    if digest((job / 'narrator.wav').read_bytes()) != narrator['sha256']:
        raise ValueError('Narrator reference changed')
    selected = plan['blocks'][args.start:args.stop]
    if args.blocks is not None:
        if args.start != 0 or args.stop is not None:
            parser.error('--blocks cannot be combined with --start or --stop')
        requested = set(args.blocks)
        available = {block['id'] for block in plan['blocks']}
        if requested - available:
            parser.error(f'Unknown block IDs: {sorted(requested - available)}')
        selected = [block for block in plan['blocks'] if block['id'] in requested]
    chunks = job / 'chunks'
    chunks.mkdir(exist_ok=True)
    engine = None
    for block in selected:
        output = chunks / f"{block['id']:04d}.wav"
        meta = output.with_suffix('.json')
        signature = digest(json.dumps({'block': block, 'narrator': narrator,
                                       'model': plan['model_revision'], 'code': plan['code_revision'],
                                       'seed_base': args.seed, 'decoder': 'float32',
                                       'context': 4096, 'temperature': 1.0, 'top_p': 0.9,
                                       'top_k': 30}, sort_keys=True))
        seed = args.seed + block['id']
        if output.exists() and meta.exists():
            previous = read_json(meta)
            if previous['signature'] != signature or digest(output.read_bytes()) != previous['sha256']:
                raise ValueError(f'Existing block differs: {output}')
            if not args.retry:
                continue
            seed = previous['seed'] + 100000
            backup = job / 'rejected' / f"{block['id']:04d}-seed-{previous['seed']}"
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(output, backup.with_suffix('.wav'))
            shutil.copy2(meta, backup.with_suffix('.json'))
        if engine is None:
            engine = load_engine(job / 'narrator.wav')
        result = synthesize(engine, block['text'], narrator['text'], output, seed)
        write_json(meta, {**result, 'signature': signature, 'block': block['id']})
        print(json.dumps({'event': 'rendered', 'block': block['id'], 'total': len(plan['blocks']),
                          'chapter': block['chapter'], **result}), flush=True)


if __name__ == '__main__':
    main()
