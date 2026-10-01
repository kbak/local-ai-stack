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
old = '''                try:
                    if dc.arg_name:'''
new = '''                try:
                    if command == "/identify":
                        result = identify_direct(dc.func, args, images, _signal, sender)
                    elif dc.arg_name:'''
assert source.count(old) == 1, "Upstream direct skills changed; review image context patch"
source = source.replace(old, new)
source = "from image_tools import invoke_with_images, identify_direct\n" + source
path.write_text(source)
