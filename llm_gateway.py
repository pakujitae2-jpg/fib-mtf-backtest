# -*- coding: utf-8 -*-
"""llm_gateway.py — OmniRoute(로컬 AI 게이트웨이) 를 이 프로젝트에서 쓰는 얇은 클라이언트.

OmniRoute 는 http://localhost:20128/v1 에서 OpenAI 호환 API 를 제공한다 (external/OmniRoute, npm 전역 설치 `omniroute`).
표준 라이브러리만 사용한다 (프로젝트 원칙: 의존성 없음).

설정 우선순위
  1) 환경변수 OMNIROUTE_BASE_URL / OMNIROUTE_API_KEY / OMNIROUTE_MODEL
  2) 프로젝트 루트의 .env.omniroute (KEY=VALUE, tools/omniroute_setup.py 가 생성)

사용 예
  import llm_gateway as G
  print(G.chat("한 단어로 답해: OK"))                       # 기본 모델 = auto (OmniRoute 라우팅)
  print(G.chat([{"role": "user", "content": "..."}], model="auto", temperature=0))
  python llm_gateway.py "질문"                              # CLI 스모크

  python report_assist.py                                  # corrected_result.txt 요약 (예시 활용)
"""
import json
import os
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(ROOT, '.env.omniroute')
DEFAULT_BASE_URL = 'http://localhost:20128'


def _load_env_file(path=ENV_FILE):
    out = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def config():
    env = _load_env_file()
    base = os.environ.get('OMNIROUTE_BASE_URL') or env.get('OMNIROUTE_BASE_URL') or DEFAULT_BASE_URL
    key = os.environ.get('OMNIROUTE_API_KEY') or env.get('OMNIROUTE_API_KEY') or ''
    model = os.environ.get('OMNIROUTE_MODEL') or env.get('OMNIROUTE_MODEL') or 'auto'
    return {'base_url': base.rstrip('/'), 'api_key': key, 'model': model}


class GatewayError(RuntimeError):
    pass


def _request(path, body=None, method='POST', timeout=120):
    cfg = config()
    url = cfg['base_url'] + path
    headers = {'Content-Type': 'application/json'}
    if cfg['api_key']:
        headers['Authorization'] = 'Bearer ' + cfg['api_key']
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')[:500]
        if e.code == 401:
            raise GatewayError('OmniRoute 인증 실패(401). .env.omniroute 의 OMNIROUTE_API_KEY 를 확인하거나 `python tools/omniroute_setup.py` 를 다시 실행: %s' % detail)
        raise GatewayError('OmniRoute HTTP %d %s: %s' % (e.code, url, detail))
    except urllib.error.URLError as e:
        raise GatewayError('OmniRoute 서버에 연결할 수 없음 (%s). `tools\\omniroute-start.cmd` 로 서버를 먼저 띄우세요: %s' % (url, e.reason))


def health():
    """서버 생존 확인 (인증 불필요)."""
    return _request('/api/health', method='GET', timeout=10)


def models():
    """게이트웨이가 노출하는 모델 id 목록."""
    r = _request('/v1/models', method='GET', timeout=30)
    return [m.get('id') for m in r.get('data', [])]


def chat(messages, model=None, temperature=0.2, max_tokens=1024, system=None, **kw):
    """OpenAI 호환 chat completion. messages 는 문자열(단일 user 메시지) 또는 [{'role','content'}] 리스트.
    반환: assistant 텍스트. 원본 응답이 필요하면 chat_raw 사용."""
    r = chat_raw(messages, model=model, temperature=temperature, max_tokens=max_tokens, system=system, **kw)
    try:
        return r['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        raise GatewayError('예상하지 못한 응답 형식: %s' % json.dumps(r)[:400])


def chat_raw(messages, model=None, temperature=0.2, max_tokens=1024, system=None, **kw):
    if isinstance(messages, str):
        messages = [{'role': 'user', 'content': messages}]
    if system:
        messages = [{'role': 'system', 'content': system}] + list(messages)
    body = {'model': model or config()['model'], 'messages': messages, 'temperature': temperature, 'max_tokens': max_tokens}
    body.update(kw)
    return _request('/v1/chat/completions', body)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    q = ' '.join(sys.argv[1:]) or '한 단어로만 답해: OK'
    cfg = config()
    print('base_url=%s model=%s key=%s' % (cfg['base_url'], cfg['model'], ('set(%s...)' % cfg['api_key'][:8]) if cfg['api_key'] else 'MISSING'))
    print('health:', health())
    print('answer:', chat(q, max_tokens=64))
