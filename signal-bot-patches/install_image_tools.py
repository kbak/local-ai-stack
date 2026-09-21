"""Apply checked patches to the pinned upstream bot during Docker build."""
from pathlib import Path

path = Path("/app/bot.py")
source = path.read_text()
old = '''                            if _imgs:
                                return await agent.invoke_async([{"text": _in}] + _imgs)
                            return await agent.invoke_async(_in)'''
new = '''                            return await invoke_with_images(agent, _in, _imgs, _signal, sender)'''
assert source.count(old) == 1, "Upstream agent invocation changed; review image context patch"
source = source.replace(old, new)
source = "from image_tools import invoke_with_images\n" + source
path.write_text(source)
