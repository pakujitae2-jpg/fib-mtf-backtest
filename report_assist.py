# -*- coding: utf-8 -*-
"""report_assist.py — OmniRoute 게이트웨이 활용 예시: 교정 결과(corrected/corrected_summary.json) 를 LLM 에게 요약시킨다.

python report_assist.py            # 기본 모델(auto) 로 한국어 요약
python report_assist.py --model glm/glm-5.2 --lang en
결과는 화면 출력 + corrected/llm_summary_<model>.md 저장. 수치 자체는 엔진 출력이 기준이며 LLM 요약은 보조 설명용이다.
"""
import argparse
import json
import os
import re
import sys
import llm_gateway as G

sys.stdout.reconfigure(encoding='utf-8')
ap = argparse.ArgumentParser()
ap.add_argument('--model', default=None)
ap.add_argument('--lang', default='ko')
ap.add_argument('--max-tokens', type=int, default=900)
a = ap.parse_args()

S = json.load(open('corrected/corrected_summary.json', encoding='utf-8'))
facts = []
for V in ('V2', 'V3'):
    v = S['versions'][V]
    L, C = v['legacy'], v['corrected']
    facts.append('%s legacy: trades %d PF %.2f return %+.0f%% MTM-MDD %.0f%% | corrected: trades %d PF %.2f return %+.0f%% MTM-MDD %.0f%% (long PF %.2f short PF %.2f)' % (
        V, L['n'], L['pf'], L['ret'], L['mtm_mdd_close'], C['n'], C['pf'], C['ret'], C['mtm_mdd_close'], C['long_pf'], C['short_pf']))
    for r in v['impact_sequential']:
        facts.append('  %s step "%s": trades %d PF %.2f return %+.0f%% added %d removed %d changed %d delta_sum_pm %+.1f' % (
            V, r['step'], r['n'], r['pf'], r['ret'], r['added'], r['removed'], r['changed'], r['delta_sum_pm']))
prompt = ('아래는 암호화폐 백테스트 엔진의 시간순서(look-ahead) 오류를 교정한 전후 결과다. 전략 파라미터는 바꾸지 않았다.\n'
          '사실만 사용해서 (1) 무엇이 바뀌었는지 (2) 어떤 오류가 성과를 얼마나 부풀렸는지 (3) 교정 후 이 전략을 어떻게 판단해야 하는지를 '
          '%s로 8문장 이내로 요약하라. 숫자는 주어진 값만 인용하라.\n\n' % ('한국어' if a.lang == 'ko' else 'English') + '\n'.join(facts))
model = a.model or G.config()['model']
print('model =', model)
text = G.chat(prompt, model=model, temperature=0.1, max_tokens=a.max_tokens)
print(text)
out = 'corrected/llm_summary_%s.md' % re.sub(r'[^A-Za-z0-9_.-]+', '_', model)
with open(out, 'w', encoding='utf-8') as f:
    f.write('# LLM 요약 (%s, OmniRoute)\n\n%s\n' % (model, text))
print('\nsaved ->', out)
