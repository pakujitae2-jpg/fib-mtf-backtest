# -*- coding: utf-8 -*-
"""tools/omniroute_setup.py — 이 프로젝트용 OmniRoute API 키를 만들고 설정 파일에 기록한다 (멱등).

전제: `npm install -g omniroute` 완료, 서버 실행 중 (tools\\omniroute-start.cmd).
동작:
  1) .env.omniroute 에 OMNIROUTE_API_KEY 가 있고 서버가 받아주면 그대로 둔다.
  2) 없으면 CLI 머신 토큰으로 POST /api/keys (label=fibmtf-project) 를 호출해 키를 만들고
     .env.omniroute 와 .claude/settings.local.json(env 블록: .mcp.json 의 ${OMNIROUTE_API_KEY} 확장용) 에 기록한다.
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, '.env.omniroute')
SETTINGS = os.path.join(ROOT, '.claude', 'settings.local.json')
BASE = os.environ.get('OMNIROUTE_BASE_URL', 'http://localhost:20128')
LABEL = 'fibmtf-project'
OMNI = os.path.join(os.environ.get('APPDATA', ''), 'npm', 'node_modules', 'omniroute', 'bin', 'omniroute.mjs')


def read_env():
    out = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                out[k.strip()] = v.strip()
    return out


def key_works(key):
    req = urllib.request.Request(BASE + '/v1/models', headers={'Authorization': 'Bearer ' + key})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return False
    except urllib.error.URLError as e:
        sys.exit('OmniRoute 서버에 연결할 수 없음 (%s): %s — tools\\omniroute-start.cmd 를 먼저 실행' % (BASE, e.reason))


def create_key():
    if not os.path.exists(OMNI):
        sys.exit('omniroute CLI 를 찾을 수 없음: %s (npm install -g omniroute)' % OMNI)
    cmd = ['node', OMNI, '--output', 'json', '--base-url', BASE, 'api', 'api-keys', 'post-api-keys', '--body', json.dumps({'name': LABEL, 'label': LABEL})]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    txt = r.stdout.strip()
    i = txt.find('{')
    if r.returncode != 0 or i < 0:
        sys.exit('키 생성 실패:\n%s\n%s' % (r.stdout[-1500:], r.stderr[-1500:]))
    data = json.loads(txt[i:])
    # 응답 형태가 {"key": {...}} 또는 {...} 일 수 있어 'key' 문자열 필드를 찾는다
    def find_key(o):
        if isinstance(o, dict):
            for k in ('key', 'apiKey', 'value', 'token'):
                v = o.get(k)
                if isinstance(v, str) and len(v) >= 16:
                    return v
            for v in o.values():
                f = find_key(v)
                if f:
                    return f
        return None
    key = find_key(data)
    if not key:
        sys.exit('응답에서 키 값을 찾지 못함: %s' % json.dumps(data)[:800])
    return key, data


def write_env(key):
    lines = ['# OmniRoute (local AI gateway) — 이 프로젝트 전용 키. 로컬 게이트웨이용이며 외부 서비스 키가 아님.',
             'OMNIROUTE_BASE_URL=%s' % BASE, 'OMNIROUTE_API_KEY=%s' % key, 'OMNIROUTE_MODEL=auto', '']
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def write_settings(key):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    cfg = {}
    if os.path.exists(SETTINGS):
        try:
            cfg = json.load(open(SETTINGS, encoding='utf-8'))
        except Exception:
            cfg = {}
    cfg.setdefault('env', {})
    cfg['env']['OMNIROUTE_API_KEY'] = key
    cfg['env']['OMNIROUTE_BASE_URL'] = BASE
    with open(SETTINGS, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    env = read_env()
    key = env.get('OMNIROUTE_API_KEY', '')
    if key and key_works(key):
        print('기존 키 유효 (%s...) — 변경 없음' % key[:10])
    else:
        key, data = create_key()
        write_env(key)
        print('새 키 발급: %s... (label=%s)' % (key[:10], LABEL))
        if not key_works(key):
            sys.exit('발급된 키로 /v1/models 인증 실패 — 대시보드 API Manager 에서 키 상태 확인')
    write_settings(key)
    print('기록: %s, %s' % (ENV_FILE, SETTINGS))
    sys.path.insert(0, ROOT)
    import llm_gateway as G
    ms = G.models()
    print('모델 %d개 (예: %s)' % (len(ms), ', '.join(ms[:5])))
    print('chat 테스트:', G.chat('Reply with the single word OK', max_tokens=16).strip())
