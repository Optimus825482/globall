with open('backend/app/routers/forex.py', 'rb') as f:
    content = f.read()

target = b'            if _AUTO_SETTINGS.fvg_pullback_enabled:\r\n'
if target not in content:
    target = b'            if _AUTO_SETTINGS.fvg_pullback_enabled:\n'
assert target in content, "Target not found in forex.py"

replacement = b'    fvg_pullback_enabled: bool = Field(False, description="FVG Imbalance Pullback motoru (Canli raporda -954 USD zarar urettigi icin kapatildi)")\r\n' if b'\r\n' in target else b'    fvg_pullback_enabled: bool = Field(False, description="FVG Imbalance Pullback motoru (Canli raporda -954 USD zarar urettigi icin kapatildi)")\n'

new_content = content.replace(target, replacement, 1)
with open('backend/app/routers/forex.py', 'wb') as f:
    f.write(new_content)
print("Line 5280 cleaned successfully.")
