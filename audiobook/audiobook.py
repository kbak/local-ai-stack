#!/usr/bin/env python3
"""Prepare and assemble on-demand audiobooks, with optional Breeze narration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.maintenance/audiobook'
VENDOR = STATE / 'vendor/breeze-tts'
MODEL = STATE / 'models/Breeze-TTS-2'
MODEL_REV = '3e28c5151381a722f1d8661b4118c298caa77aa4'
CODE_REV = '008f769016b0a24711becd7a4925030bc93f608c'
GPU = os.environ.get('CUDA_VISIBLE_DEVICES', '0')
DEFAULT_VOICE = ('A clear audiobook narrator with natural conversational intonation. '
                 'Measured delivery, clear consonants, and gentle pauses between ideas. '
                 'Clean studio recording.')
REFERENCE_TEXT = ('Every story begins with a first step. Along the way, we discover new places, '
                  'meet unfamiliar people, and learn to see familiar things differently. '
                  'Take your time and listen as the next chapter unfolds.')


def digest(value):
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def pronounce(text, pronunciations):
    for key, value in pronunciations.items():
        text = re.sub(r'\b' + re.escape(key) + r'\b', value, text, flags=re.IGNORECASE)
    return text


def split_paragraph(text, max_words=95):
    """Split only at sentence boundaries and assert that every source word survives."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current = [], []
    for sentence in sentences:
        if current and len((' '.join(current) + ' ' + sentence).split()) > max_words:
            chunks.append(' '.join(current))
            current = []
        current.append(sentence)
    if current:
        chunks.append(' '.join(current))
    assert ' '.join(chunks).split() == text.split()
    return chunks


def prepare(args):
    job = Path(args.job).resolve()
    job.mkdir(parents=True, exist_ok=True)
    pronunciations = read_json(args.pronunciations) if args.pronunciations else {}
    if not isinstance(pronunciations, dict) or not all(
            isinstance(k, str) and k and isinstance(v, str) for k, v in pronunciations.items()):
        raise ValueError('Pronunciations must be a JSON object mapping nonempty words to strings')
    source = Path(args.source).read_bytes()
    text = source.decode('utf-8')
    spoken = text.split('FULL SPOKEN SCRIPT', 1)[-1]
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', spoken)
                  if p.strip() and not re.fullmatch(r'[=\s]+', p)]
    blocks, chapters = [], []
    chapter = None
    for paragraph in paragraphs:
        paragraph = ' '.join(paragraph.split())
        match = re.match(r'CHAPTER (\d+):\s*(.*)', paragraph)
        if match:
            chapter = int(match[1])
            title = match[2].capitalize()
            chapters.append({'number': chapter, 'title': title, 'first_block': len(blocks)})
            segments = [f'Chapter {chapter}. {title}.']
        else:
            if chapter is None:
                raise ValueError('Spoken text must begin with a chapter heading')
            segments = split_paragraph(paragraph)
        for i, segment in enumerate(segments):
            blocks.append({'id': len(blocks), 'chapter': chapter, 'heading': bool(match),
                           'source_text': segment, 'text': pronounce(segment, pronunciations),
                           'pause_after': 1.4 if match else (0.65 if i == len(segments)-1 else 0.25)})
    model_info = ({'model': 'fishaudio/s2-pro',
                   'model_revision': '1de9996b6be38b745688de084d87a5633f714e4e',
                   'code_revision': '214da3cd841bda85da2496b96cd3c4d7edb1337e'}
                  if args.engine == 'fish' else
                  {'model': 'BreezeBlue/Breeze-TTS-2', 'model_revision': MODEL_REV,
                   'code_revision': CODE_REV})
    plan = {'source': str(Path(args.source).resolve()), 'source_sha256': digest(source),
            'title': args.title or Path(args.source).stem,
            **model_info, 'pronunciations': pronunciations,
            'chapters': chapters, 'blocks': blocks}
    if (job / 'plan.json').exists() and read_json(job / 'plan.json') != plan:
        raise ValueError('Existing job differs; use a new directory instead of overwriting audio')
    (job / 'source.txt').write_bytes(source)
    (job / 'narration.txt').write_text('\n\n'.join(b['text'] for b in blocks) + '\n')
    write_json(job / 'plan.json', plan)
    print(json.dumps({'job': str(job), 'chapters': len(chapters), 'blocks': len(blocks),
                      'spoken_words': sum(len(b['text'].split()) for b in blocks)}), flush=True)


def load_engine(fast=False):
    # Set before importing torch. Refuse silently falling back to CPU or another GPU.
    os.environ['CUDA_VISIBLE_DEVICES'] = GPU
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    sys.path.insert(0, str(VENDOR))
    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError('Select exactly one available CUDA GPU with CUDA_VISIBLE_DEVICES')
    torch.set_num_threads(4)
    free, total = torch.cuda.mem_get_info()
    if free < (19 if fast else 12) * 1024**3:
        raise RuntimeError(f'Insufficient free VRAM: {free / 1024**3:.1f} GiB')
    # Limit this worker to 24 GiB, leaving room for other resident services.
    torch.cuda.set_per_process_memory_fraction(min(24 * 1024**3 / total, 1.0))
    from breeze_infer.runtime import load_runtime, update_generation_config_for_breeze
    from models.fast_streaming import FastBreezeStreamingRuntime, FastStreamingConfig
    tokenizer, model, codec = load_runtime(MODEL, device='cuda:0', attn_implementation='eager')
    update_generation_config_for_breeze(model)
    runtime = FastBreezeStreamingRuntime(model, codec, FastStreamingConfig(
        max_new_tokens=1500, max_seq_len=2048, fast_all=fast,
        repetition_penalty=1.1), tokenizer=tokenizer)
    if fast:
        from dataclasses import replace

        from models.warmup_profile import load_warmup_profile
        profile = replace(load_warmup_profile(VENDOR / 'configs/fast.json'),
                          codec_chunk_frames=runtime.codec_chunk_frames,
                          freeze_after_warmup=False)
        runtime.warmup_from_profile(profile)
    print(json.dumps({'event': 'model_loaded', 'device': torch.cuda.get_device_name(),
                      'fast': fast, 'allocated_GiB': torch.cuda.memory_allocated()/1024**3}), flush=True)
    return tokenizer, model, codec, runtime


def synthesize(engine, text, output, seed, instruction=None, reference=None, ref_text=None):
    import numpy as np
    import soundfile as sf
    import torch
    from breeze_infer.runtime import set_all_seeds
    from breeze_infer.templates import (
        get_template,
        prepare_inputs,
        select_template_name,
    )
    tokenizer, model, codec, runtime = engine
    request = {'id': output.stem, 'text': text, 'speaker': 'S0'}
    if instruction:
        request['instruction'] = instruction
    if reference:
        request.update(ref_audio_path=str(reference), ref_text=ref_text)
    set_all_seeds(seed)
    started = time.monotonic()
    with torch.inference_mode():
        inputs = prepare_inputs(tokenizer, codec, model, [request],
                                get_template(select_template_name(request)),
                                guidance_scale=4.0 if instruction else 1.0,
                                guidance_scale_ref=None, guidance_scale_ins=None)
        chunks, frames = [], 0
        for chunk in runtime.iter_audio_chunks(inputs, request_id=output.stem, seed=seed):
            chunks.append(chunk.audio)
            frames += chunk.codec_frames
    audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
    if frames >= 1500 or not len(audio) or not np.isfinite(audio).all():
        raise RuntimeError(f'Invalid or truncated generation: {output.name}, {frames} frames')
    duration = len(audio) / runtime.sample_rate
    wpm = len(text.split()) / duration * 60
    if len(text.split()) > 15 and not 65 < wpm < 260:
        raise RuntimeError(f'Implausible duration: {duration:.1f}s for {len(text.split())} words')
    peak = float(np.max(np.abs(audio)))
    if peak > 0.999:
        audio *= 0.98 / peak
    tmp = output.with_suffix('.tmp.wav')
    sf.write(tmp, audio, runtime.sample_rate, subtype='PCM_24')
    tmp.replace(output)
    return {'seconds': duration, 'sample_rate': runtime.sample_rate,
            'frames': len(audio), 'generation_seconds': time.monotonic()-started,
            'seed': seed, 'words_per_minute': wpm,
            'peak_before_scaling': peak, 'sha256': digest(output.read_bytes()),
            'peak_allocated_GiB': torch.cuda.max_memory_allocated()/1024**3}


def voice(args):
    job = Path(args.job).resolve()
    job.mkdir(parents=True, exist_ok=True)
    output = job / 'narrator.wav'
    if output.exists():
        raise ValueError('Narrator already exists; preserve it for consistent chapter voices')
    engine = load_engine(args.fast)
    result = synthesize(engine, REFERENCE_TEXT, output, args.seed,
                        instruction=args.instruction or DEFAULT_VOICE)
    write_json(job / 'narrator.json', {**result, 'text': REFERENCE_TEXT,
                                      'instruction': args.instruction or DEFAULT_VOICE})
    print(json.dumps({'event': 'voice_ready', **result}), flush=True)


def render(args):
    job = Path(args.job).resolve()
    plan, narrator = read_json(job / 'plan.json'), read_json(job / 'narrator.json')
    if digest((job / 'narrator.wav').read_bytes()) != narrator['sha256']:
        raise RuntimeError('Narrator reference changed')
    chunks = job / 'chunks'
    chunks.mkdir(exist_ok=True)
    engine = None
    blocks = plan['blocks'][args.start:args.stop]
    for block in blocks:
        output = chunks / f"{block['id']:04d}.wav"
        meta = output.with_suffix('.json')
        signature = digest(json.dumps({'block': block, 'narrator': narrator,
                                       'model': MODEL_REV, 'code': CODE_REV, 'seed': args.seed,
                                       'fast': args.fast}, sort_keys=True))
        if output.exists() and meta.exists():
            previous = read_json(meta)
            if previous['signature'] != signature:
                raise ValueError(f'Render settings changed for {output}; use a new job')
            if digest(output.read_bytes()) != previous['sha256']:
                raise ValueError(f'Audio checksum mismatch: {output}')
            continue
        if engine is None:
            engine = load_engine(args.fast)
        result = synthesize(engine, block['text'], output, args.seed + block['id'],
                            reference=job / 'narrator.wav', ref_text=narrator['text'])
        write_json(meta, {**result, 'signature': signature, 'block': block['id']})
        print(json.dumps({'event': 'rendered', 'block': block['id'], 'total': len(plan['blocks']),
                          'chapter': block['chapter'], **result}), flush=True)


def timestamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d}.{ms%1000:03d}'


def metadata_escape(text):
    return ''.join('\\' + c if c in '\\=;#\n' else c for c in text)


def assemble(args):
    import numpy as np
    import soundfile as sf
    job = Path(args.job).resolve()
    plan = read_json(job / 'plan.json')
    raw_master = job / 'audiobook_unmastered.flac'
    master = job / 'audiobook.flac'
    first_id = plan['blocks'][0]['id']
    sample_rate = read_json(job / 'chunks' / f'{first_id:04d}.json')['sample_rate']
    chapters, total_frames = [], 0
    tmp = raw_master.with_suffix('.tmp.flac')
    with sf.SoundFile(tmp, 'w', samplerate=sample_rate, channels=1, subtype='PCM_24') as out:
        for block in plan['blocks']:
            path = job / 'chunks' / f"{block['id']:04d}.wav"
            meta = read_json(path.with_suffix('.json'))
            if digest(path.read_bytes()) != meta['sha256']:
                raise RuntimeError(f'Audio checksum mismatch: {path}')
            data, sr = sf.read(path, dtype='float32')
            if sr != sample_rate or len(data) != meta['frames']:
                raise RuntimeError(f'Unexpected audio format: {path}')
            if block['heading']:
                chapter = next(c for c in plan['chapters'] if c['number'] == block['chapter'])
                chapters.append({**chapter, 'start_seconds': total_frames/sample_rate})
            out.write(data)
            silence = np.zeros(round(block['pause_after']*sample_rate), dtype=np.float32)
            out.write(silence)
            total_frames += len(data) + len(silence)
    tmp.replace(raw_master)
    duration = total_frames/sample_rate
    for i, chapter in enumerate(chapters):
        chapter['end_seconds'] = chapters[i+1]['start_seconds'] if i+1 < len(chapters) else duration
    write_json(job / 'chapters.json', chapters)
    (job / 'chapters.txt').write_text('\n'.join(
        f"{timestamp(c['start_seconds'])}  Chapter {c['number']}: {c['title']}" for c in chapters)+'\n')
    metadata = [';FFMETADATA1', 'title=' + metadata_escape(plan['title']),
                'artist=' + metadata_escape('Synthetic narration — ' + plan['model']),
                'comment=Synthetic audiobook narration']
    # Explicit Vorbis chapter tags avoid the observed one-second offsets when
    # the installed Ogg muxer converts AVChapters.
    for i, c in enumerate(chapters, 1):
        metadata += [f"CHAPTER{i:03d}={timestamp(c['start_seconds'])}",
                     f"CHAPTER{i:03d}NAME=" + metadata_escape(
                         f"Chapter {c['number']}: {c['title']}")]
    for c in chapters:
        metadata += ['[CHAPTER]', 'TIMEBASE=1/1000',
                     f"START={round(c['start_seconds']*1000)}",
                     f"END={round(c['end_seconds']*1000)}",
                     'title=' + metadata_escape(f"Chapter {c['number']}: {c['title']}")]
    metadata_path = job / 'chapters.ffmetadata'
    metadata_path.write_text('\n'.join(metadata) + '\n')
    # Measure once, then apply a constant gain. Preserve the original dynamics
    # when the -19 LUFS target would require peak limiting or compression.
    analysis = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', str(raw_master),
                               '-af', 'loudnorm=I=-19:TP=-2:LRA=11:print_format=json',
                               '-f', 'null', '-'], capture_output=True, text=True, check=True)
    levels = json.loads(analysis.stderr[analysis.stderr.rfind('{'):])
    write_json(job / 'loudness-input.json', levels)
    gain = min(-19-float(levels['input_i']), -2-float(levels['input_tp']))
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-y', '-i', str(raw_master),
                    '-af', f'volume={gain}dB', '-ar', str(sample_rate), '-c:a', 'flac',
                    str(master)], capture_output=True, text=True, check=True)
    write_json(job / 'loudness-output.json', {'method': 'constant_gain', 'gain_db': gain,
               'expected_integrated_lufs': float(levels['input_i'])+gain,
               'expected_true_peak_dbtp': float(levels['input_tp'])+gain})
    command = ['ffmpeg', '-nostdin', '-hide_banner', '-y', '-i', str(master),
               '-i', str(metadata_path), '-map', '0:a', '-map_metadata', '1', '-map_chapters', '-1',
               '-c:a', 'libopus', '-b:a', '256k', '-application', 'audio', '-vbr', 'on']
    output = job / 'audiobook.ogg'
    command.append(str(output))
    subprocess.run(command, check=True)
    write_json(job / 'result.json', {'duration_seconds': duration, 'chapters': len(chapters),
                                   'blocks': len(plan['blocks']), 'ogg': str(output),
                                   'lossless_master': str(master),
                                   'model_revision': plan['model_revision']})
    print(json.dumps({'event': 'assembled', 'seconds': duration, 'ogg': str(output)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('source')
    p.add_argument('job')
    p.add_argument('--title', help='Book title; defaults to the source filename stem')
    p.add_argument('--pronunciations', help='JSON file mapping words to spoken replacements')
    p.add_argument('--engine', choices=['breeze', 'fish'], default='breeze')
    p.set_defaults(func=prepare)
    p = sub.add_parser('voice')
    p.add_argument('job')
    p.add_argument('--instruction')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--fast', action='store_true')
    p.set_defaults(func=voice)
    p = sub.add_parser('render')
    p.add_argument('job')
    p.add_argument('--seed', type=int, default=1000)
    p.add_argument('--start', type=int, default=0)
    p.add_argument('--stop', type=int)
    p.add_argument('--fast', action='store_true')
    p.set_defaults(func=render)
    p = sub.add_parser('assemble')
    p.add_argument('job')
    p.set_defaults(func=assemble)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
