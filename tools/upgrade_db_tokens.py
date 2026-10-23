#!/usr/bin/env python3
import re
from pathlib import Path

path = Path("/data/data/com.termux/files/home/public_ai_gateway.py")
text = path.read_text()
original = text

if "import gateway_tokens" not in text:
    if "import urllib.parse\n" not in text:
        raise SystemExit("import anchor not found")
    text = text.replace(
        "import urllib.parse\n",
        "import urllib.parse\n\nimport gateway_tokens\n",
        1,
    )

match = re.search(r"VALID_KEYS\s*=\s*\{.*?\}", text, re.S)
if not match:
    raise SystemExit("VALID_KEYS block not found")
static_keys = [
    key
    for key in re.findall(r'"([^"]+)"', match.group(0))
    if key.startswith("qg_live_")
]
if not static_keys:
    raise SystemExit("no qg_live_ owner keys found")
replacement = "STATIC_KEYS = {\n" + "".join(
    f'    "{key}",  # 用户 Qoder Key\n' for key in static_keys
) + "}"
text = text[: match.start()] + replacement + text[match.end():]
text = text.replace(
    "# 授权可访问的 API Key 列表（包含主 Key 与朋友专属 Key）",
    "# 内部静态 Key（仅用户本人 Qoder Key）；朋友 Key 走 SQLite 哈希 token",
)

old_verify = '''    def verify_auth(self) -> bool:
        auth_header = self.headers.get("Authorization", "").strip()
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[7:].strip()
        return token in VALID_KEYS
'''
new_verify = '''    def verify_auth(self) -> bool:
        auth_header = self.headers.get("Authorization", "").strip()
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[7:].strip()
        if token in STATIC_KEYS:
            return True
        ok, _, _ = gateway_tokens.verify_token(token, self.get_client_ip())
        return ok
'''
if old_verify not in text:
    raise SystemExit("verify_auth block not found")
text = text.replace(old_verify, new_verify, 1)

if "gateway_tokens.init_db()" not in text:
    anchor = '    print("=" * 60)\n    http_server = ThreadingHTTPServer'
    if anchor not in text:
        raise SystemExit("main anchor not found")
    text = text.replace(
        anchor,
        '    print("=" * 60)\n    gateway_tokens.init_db()\n'
        '    print("[*] Token 鉴权: SQLite 哈希存储 (可吊销/可审计)")\n'
        '    http_server = ThreadingHTTPServer',
        1,
    )

backup = Path("/data/data/com.termux/files/home/public_ai_gateway.py.bak-tokenupgrade")
if not backup.exists():
    backup.write_text(original)
path.write_text(text)
print("GATEWAY_TOKEN_UPGRADE_OK")
