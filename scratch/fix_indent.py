with open('backend/app/routers/forex.py', 'rb') as f:
    content = f.read()

target = b'                    active_strats = []\r\n            if _AUTO_SETTINGS.fvg_pullback_enabled:\r\n                        active_strats.append("FVG Pullback")\r\n'
if target not in content:
    target = b'                    active_strats = []\n            if _AUTO_SETTINGS.fvg_pullback_enabled:\n                        active_strats.append("FVG Pullback")\n'
assert target in content, "Target not found"

replacement = b'                    active_strats = []\r\n                    if _AUTO_SETTINGS.fvg_pullback_enabled:\r\n                        active_strats.append("FVG Pullback")\r\n' if b'\r\n' in target else b'                    active_strats = []\n                    if _AUTO_SETTINGS.fvg_pullback_enabled:\n                        active_strats.append("FVG Pullback")\n'

new_content = content.replace(target, replacement, 1)
with open('backend/app/routers/forex.py', 'wb') as f:
    f.write(new_content)
print("Indentation fixed.")
