"""Apply the pinned bot patches, failing the build when upstream context differs."""

from pathlib import Path
import shutil
import subprocess
import sysconfig
import tempfile

PATCHES = Path(__file__).resolve().parent


def apply_patches(app: Path, site_packages: Path) -> None:
    # Normalize upstream CRLF in a scratch tree. Validate both patches before
    # replacing any source, and never modify the upstream checkout itself.
    targets = {
        'bot.py': app / 'bot.py',
        'agent.py': app / 'agent.py',
        'config.py': app / 'config.py',
        'skills/registry.py': app / 'skills/registry.py',
        'strands/models/openai.py': site_packages / 'strands/models/openai.py',
    }
    with tempfile.TemporaryDirectory(prefix='bot-patches-') as directory:
        root = Path(directory)
        for relative, target in targets.items():
            staged = root / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(target.read_text())
        patches = [str(PATCHES / name) for name in ('uoltz.patch', 'strands-openai.patch')]
        subprocess.run(['git', 'apply', '--check', *patches], cwd=root, check=True)
        subprocess.run(['git', 'apply', *patches], cwd=root, check=True)
        for relative, target in targets.items():
            compile((root / relative).read_text(), str(target), 'exec')
        for relative, target in targets.items():
            shutil.copyfile(root / relative, target)


if __name__ == '__main__':
    apply_patches(Path('/app'), Path(sysconfig.get_paths()['purelib']))
