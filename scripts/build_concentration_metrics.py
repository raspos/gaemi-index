"""
scripts/build_concentration_metrics.py

개미 지수 전면 재기획 — 개인 순매수 집중도(GAEMI CONCENTRATION) 및 이동 데이터 생성
- 관측 주기: 최근 20거래일 롤링 윈도우
- 산식: 최근 20거래일 순매수 상위 10종목 합계 / 최근 20거래일 순매수 양(+)인 전체 종목 합계 * 100
- 요인 분해: 종목별 기여도(합계 = 집중도 변화), 20거래일 롤링 진입/제외 효과, 분모 변화 효과
- 업종 구성 및 이동: 20거래일 vs 직전 20거래일 비중 비교, 상승/하락 종목
- 단기 순위: 당일(1D), 최근 5거래일(5D), 20거래일(20D) 순위
- BOK WATCH형 변곡점 및 이벤트 마커 추출
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.ledger_loader import load_raw_ledger
DATA_DIR = os.path.join(BASE_DIR, "data")
DOCS_DATA_DIR = os.path.join(BASE_DIR, "docs", "data")
OUTPUT_JSON = os.path.join(DATA_DIR, "gaemi_concentration.json")
OUTPUT_JS = os.path.join(DOCS_DATA_DIR, "gaemi_concentration.js")


def classify_sector(code, name, ind):
    code = str(code).zfill(6)
    name = str(name)
    ind = str(ind)

    # 반도체
    if code in ['005930', '005935', '000660', '042700', '000150']:
        return '반도체'
    if '반도체' in ind or '반도체' in name:
        return '반도체'

    # 전자부품 / IT기기
    if code in ['009150', '353200', '222800', '007660', '011070', '108320']:
        return '전자부품/IT'
    if '전자부품' in ind or '인쇄회로' in ind:
        return '전자부품/IT'

    # 2차전지
    if code in ['373220', '006400', '051910', '086520', '247540', '003670', '096770', '005070']:
        return '2차전지'
    if '이차전지' in ind or '일차전지 및 이차전지' in ind or '축전지' in ind or '2차전지' in name or '에코프로' in name or '엘앤에프' in name or '포스코퓨처엠' in name:
        return '2차전지'

    # 바이오 / 제약
    if code in ['207940', '068270', '195940', '302440', '185750', '028300', '328130']:
        return '바이오/제약'
    if '의약' in ind or '의료' in ind or '바이오' in name or '제약' in name or '생물' in ind:
        return '바이오/제약'

    # 자동차 / 부품
    if code in ['005380', '000270', '012330', '204320']:
        return '자동차/부품'
    if '자동차' in ind or '차량' in ind:
        return '자동차/부품'

    # 플랫폼 / 소프트웨어
    if code in ['035420', '035720', '036570', '251270']:
        return '플랫폼/소프트웨어'
    if '소프트웨어' in ind or '컴퓨터 프로그래밍' in ind or '포털' in ind or '인터넷' in ind:
        return '플랫폼/소프트웨어'

    # 로봇 / AI
    if code in ['277810', '454910', '399840']:
        return '로봇/AI'
    if '로봇' in ind or '로봇' in name:
        return '로봇/AI'

    # 화학 / 소재
    if '화학' in ind or '석유' in ind or '고무' in ind or '플라스틱' in ind:
        return '화학/소재'

    # 철강 / 금속
    if '철강' in ind or '금속' in ind:
        return '철강/금속'

    # 금융 / 지주
    if '금융' in ind or '은행' in ind or '증권' in ind or '보험' in ind or '지주' in ind or '투자' in ind:
        return '금융/지주'

    # 기계 / 중공업
    if '기계' in ind or '장비' in ind or '조선' in ind or '항공' in ind or '엔진' in ind:
        return '기계/중공업'

    # 엔터 / 미디어
    if '통신' in ind or '방송' in ind or '엔터' in name or '영화' in ind or '음악' in ind or '게임' in ind:
        return '엔터/미디어'

    return '기타'


def generate_summary(date_str, conc, delta, top10_list, contribs, drop_effect, total_pos, prev_total_pos):
    """
    사전 정의된 규칙 기반의 객관적 한국어 문장 생성.
    인위적 수식어나 AI식 표현('주목할 만합니다' 등)을 배제하고 사실 데이터 위주로 작성.
    """
    top1 = top10_list[0] if len(top10_list) > 0 else None
    top2 = top10_list[1] if len(top10_list) > 1 else None

    # 기여도 상위 / 하위
    pos_c = [c for c in contribs if c['contrib'] > 0.1]
    neg_c = [c for c in contribs if c['contrib'] < -0.1]

    # 제외일 대규모 기록 탈락 효과 확인
    if drop_effect and drop_effect.get('is_dominant'):
        stock = drop_effect['name']
        drop_val_eok = drop_effect['drop_val'] / 1e8
        return (
            f"개인 순매수 집중도가 전일 대비 {delta:+.1f}%p 변화한 {conc:.1f}%를 기록했습니다. "
            f"{stock}의 경우 당일 순매매보다 20거래일 전 대규모 순매수 기록({drop_val_eok:,.0f}억원)이 "
            f"계산 대상에서 제외된 영향이 컸습니다."
        )

    if abs(delta) < 0.3:
        if top1:
            return (
                f"개인 순매수 집중도는 {conc:.1f}%로 전일과 비슷한 수준을 보였습니다. "
                f"{top1['name']}이 순매수 비중 {top1['share']:.1f}%로 1위를 유지했습니다."
            )
        return f"개인 순매수 집중도는 {conc:.1f}%로 전일과 큰 변동이 없었습니다."

    if delta >= 0.3:
        # 상승
        if len(pos_c) >= 2:
            return (
                f"개인 순매수 집중도가 전일 대비 {delta:+.1f}%p 상승한 {conc:.1f}%를 기록했습니다. "
                f"{pos_c[0]['name']}({pos_c[0]['contrib']:+.1f}%p)과 {pos_c[1]['name']}({pos_c[1]['contrib']:+.1f}%p)의 "
                f"순매수 비중이 확대되면서 상위 10종목 집중도가 높아졌습니다."
            )
        elif len(pos_c) == 1:
            return (
                f"개인 순매수 집중도가 전일 대비 {delta:+.1f}%p 상승한 {conc:.1f}%를 기록했습니다. "
                f"{pos_c[0]['name']}({pos_c[0]['contrib']:+.1f}%p)으로의 순매수 집중이 두드러졌습니다."
            )
        else:
            return (
                f"개인 순매수 집중도가 전일 대비 {delta:+.1f}%p 상승한 {conc:.1f}%를 기록했습니다. "
                f"상위권 종목들로 순매수 유입이 집중되었습니다."
            )
    else:
        # 하락
        if len(neg_c) >= 1:
            main_drops = ", ".join([c['name'] for c in neg_c[:2]])
            return (
                f"개인 순매수 집중도가 전일 대비 {delta:+.1f}%p 하락한 {conc:.1f}%를 기록했습니다. "
                f"{main_drops} 등의 비중이 축소되며 순매수 대상이 여러 종목으로 분산되었습니다."
            )
        else:
            return (
                f"개인 순매수 집중도가 전일 대비 {delta:+.1f}%p 하락한 {conc:.1f}%를 기록했습니다. "
                f"상위 종목 비중이 줄고 순매수 대상이 상대적으로 분산되었습니다."
            )


def main():
    t0 = time.time()
    print("[1/5] 원장 및 유니버스 로드...")
    uni_path = os.path.join(DATA_DIR, "universe.parquet")
    if not os.path.exists(uni_path):
        raise FileNotFoundError(f"Universe file not found: {uni_path}")
    uni = pd.read_parquet(uni_path)
    
    code_to_name = dict(zip(uni['Code'], uni['Name']))
    code_to_mkt = dict(zip(uni['Code'], uni['MarketName']))
    code_to_sec = {
        row['Code']: classify_sector(row['Code'], row['Name'], row['Industry'])
        for _, row in uni.iterrows()
    }

    trades = load_raw_ledger(['code', 'date', 'reg_close', 'krx_ind_net_vol'], verify_integrity=True)
    trades['net_val'] = trades['krx_ind_net_vol'] * trades['reg_close']
    trading_dates = sorted(trades['date'].unique())
    print(f"  원장 레코드: {len(trades):,}건, 거래일: {len(trading_dates)}일 ({trading_dates[0]} ~ {trading_dates[-1]})")

    print("[2/5] 피벗 매트릭스 생성 및 롤링 계산...")
    # 날짜 x 종목 피벗
    mat = trades.pivot(index='date', columns='code', values='net_val').fillna(0.0)
    all_codes = list(mat.columns)
    
    # 20거래일 롤링 합계
    rolling_20 = mat.rolling(20).sum()
    rolling_5 = mat.rolling(5).sum()

    # 계산 가능 시작점 (최소 20거래일 확보)
    valid_dates = trading_dates[19:]
    print(f"  유효 계산일: {len(valid_dates)}일 ({valid_dates[0]} ~ {valid_dates[-1]})")

    history = []
    daily_details = {}
    inflections = []
    lane_stock = []
    lane_sector = []
    lane_turnover = []

    prev_conc = None
    prev_top10_dict = {} # code -> share
    prev_total_pos = 0.0

    print("[3/5] 일별 집중도, 요인분해, 업종구성 계산...")
    for idx_d, d in enumerate(valid_dates):
        d_idx_full = trading_dates.index(d)
        row_20 = rolling_20.loc[d]
        row_1d = mat.loc[d]
        row_5d = rolling_5.loc[d]

        # 양(+)인 종목만 선별
        pos_series = row_20[row_20 > 0.0]
        total_pos = float(pos_series.sum())

        if total_pos <= 0:
            conc = 0.0
            top10_series = pd.Series(dtype=float)
            top10_sum = 0.0
        else:
            top10_series = pos_series.nlargest(10)
            top10_sum = float(top10_series.sum())
            conc = float(round((top10_sum / total_pos) * 100.0, 2))

        delta_conc = float(round(conc - prev_conc, 2)) if prev_conc is not None else 0.0

        # Top 10 목록 구성
        top10_list = []
        curr_top10_dict = {}
        for rank, (c, val) in enumerate(top10_series.items(), 1):
            share = float(round((val / total_pos) * 100.0, 2)) if total_pos > 0 else 0.0
            prev_s = prev_top10_dict.get(c, 0.0)
            diff_s = float(round(share - prev_s, 2))
            is_new = c not in prev_top10_dict
            curr_top10_dict[c] = share

            top10_list.append({
                'rank': rank,
                'code': c,
                'name': code_to_name.get(c, c),
                'market': code_to_mkt.get(c, '-'),
                'sector': code_to_sec.get(c, '기타'),
                'net_val': float(round(val, 0)),
                'share': share,
                'diff_share': diff_s,
                'is_new': is_new
            })

        # 종목별 기여도 분해:
        # contrib_i = w_{i,t} - w_{i,t-1} where w is share in Top10 (0 if not in Top10)
        # Sum of contrib_i over union of Top10(t) and Top10(t-1) EXACTLY equals delta_conc!
        contrib_stocks = []
        all_top_codes = set(curr_top10_dict.keys()).union(set(prev_top10_dict.keys()))
        for c in all_top_codes:
            w_curr = curr_top10_dict.get(c, 0.0)
            w_prev = prev_top10_dict.get(c, 0.0)
            c_diff = float(round(w_curr - w_prev, 2))
            if abs(c_diff) >= 0.01:
                contrib_stocks.append({
                    'code': c,
                    'name': code_to_name.get(c, c),
                    'sector': code_to_sec.get(c, '기타'),
                    'contrib': c_diff,
                    'share_now': w_curr,
                    'share_prev': w_prev,
                    'in_top10': c in curr_top10_dict
                })
        contrib_stocks.sort(key=lambda x: abs(x['contrib']), reverse=True)

        # 20거래일 이동창 효과 (신규 거래일 vs 제외 거래일)
        # d_idx_full: new day added
        # d_idx_full - 20: old day dropped
        drop_effect = None
        if d_idx_full >= 20 and contrib_stocks:
            drop_date = trading_dates[d_idx_full - 20]
            # Check the stock with largest negative contrib or largest drop in 20D sum
            largest_drop_c = min(contrib_stocks, key=lambda x: x['contrib'])
            if largest_drop_c['contrib'] <= -0.5:
                c_code = largest_drop_c['code']
                val_new = float(mat.loc[d, c_code])
                val_drop = float(mat.loc[drop_date, c_code])
                # If dropped value was large and explains the reduction
                if val_drop > 2e10 and (val_drop > 1.5 * max(val_new, 0)):
                    drop_effect = {
                        'is_dominant': True,
                        'code': c_code,
                        'name': largest_drop_c['name'],
                        'new_val': val_new,
                        'drop_val': val_drop,
                        'drop_date': drop_date
                    }

        # 업종별 순매수 구성 (양의 순매수 종목 기준, 합계 100%)
        sector_sums = {}
        for c, val in pos_series.items():
            sec = code_to_sec.get(c, '기타')
            sector_sums[sec] = sector_sums.get(sec, 0.0) + val

        sector_shares = []
        if total_pos > 0:
            for sec, s_val in sector_sums.items():
                s_share = float(round((s_val / total_pos) * 100.0, 2))
                sector_shares.append({'sector': sec, 'amount': float(round(s_val, 0)), 'share': s_share})
            sector_shares.sort(key=lambda x: x['share'], reverse=True)

        # 당일(1D) 및 5거래일(5D) 순위 (양의 순매수 기준)
        top_1d = []
        pos_1d = row_1d[row_1d > 0.0]
        tot_1d = float(pos_1d.sum())
        if tot_1d > 0:
            for rk, (c, val) in enumerate(pos_1d.nlargest(10).items(), 1):
                top_1d.append({
                    'rank': rk,
                    'code': c,
                    'name': code_to_name.get(c, c),
                    'market': code_to_mkt.get(c, '-'),
                    'sector': code_to_sec.get(c, '기타'),
                    'net_val': float(round(val, 0)),
                    'share': float(round((val / tot_1d) * 100.0, 2))
                })

        top_5d = []
        pos_5d = row_5d[row_5d > 0.0]
        tot_5d = float(pos_5d.sum())
        if tot_5d > 0:
            for rk, (c, val) in enumerate(pos_5d.nlargest(10).items(), 1):
                top_5d.append({
                    'rank': rk,
                    'code': c,
                    'name': code_to_name.get(c, c),
                    'market': code_to_mkt.get(c, '-'),
                    'sector': code_to_sec.get(c, '기타'),
                    'net_val': float(round(val, 0)),
                    'share': float(round((val / tot_5d) * 100.0, 2))
                })

        # 직전 20거래일 비중과의 비교 (비중 이동: Non-overlapping 20D comparison)
        sector_shift = []
        stock_gainers = []
        stock_losers = []
        if d_idx_full >= 39: # 40 trading days available
            prior_20_date = trading_dates[d_idx_full - 20]
            row_prior_20 = rolling_20.loc[prior_20_date]
            pos_prior = row_prior_20[row_prior_20 > 0.0]
            tot_prior = float(pos_prior.sum())
            if tot_prior > 0 and total_pos > 0:
                # 업종 비교
                prior_sec_sums = {}
                for c, val in pos_prior.items():
                    sec = code_to_sec.get(c, '기타')
                    prior_sec_sums[sec] = prior_sec_sums.get(sec, 0.0) + val
                
                all_secs = set(sector_sums.keys()).union(set(prior_sec_sums.keys()))
                for sec in all_secs:
                    curr_s = (sector_sums.get(sec, 0.0) / total_pos) * 100.0
                    prior_s = (prior_sec_sums.get(sec, 0.0) / tot_prior) * 100.0
                    diff_s = float(round(curr_s - prior_s, 2))
                    sector_shift.append({
                        'sector': sec,
                        'current_share': float(round(curr_s, 2)),
                        'prior_share': float(round(prior_s, 2)),
                        'diff': diff_s
                    })
                sector_shift.sort(key=lambda x: x['diff'], reverse=True)

                # 종목 비교
                all_c = set(pos_series.index).union(set(pos_prior.index))
                stock_diffs = []
                for c in all_c:
                    curr_w = (pos_series.get(c, 0.0) / total_pos) * 100.0
                    prior_w = (pos_prior.get(c, 0.0) / tot_prior) * 100.0
                    diff_w = curr_w - prior_w
                    if abs(diff_w) >= 0.1:
                        stock_diffs.append({
                            'code': c,
                            'name': code_to_name.get(c, c),
                            'sector': code_to_sec.get(c, '기타'),
                            'current_share': float(round(curr_w, 2)),
                            'prior_share': float(round(prior_w, 2)),
                            'diff': float(round(diff_w, 2))
                        })
                stock_diffs.sort(key=lambda x: x['diff'], reverse=True)
                stock_gainers = stock_diffs[:5]
                stock_losers = stock_diffs[-5:][::-1]

        # 자동 설명문 생성
        summary = generate_summary(
            d, conc, delta_conc, top10_list, contrib_stocks, drop_effect, total_pos, prev_total_pos
        )

        # 변곡점 및 이벤트 감지
        is_inflection = abs(delta_conc) >= 2.5
        events = []
        # 1) 종목 집중: 상위 종목 중 기여도 >= 2.0%p
        top_contrib = max([c['contrib'] for c in contrib_stocks], default=0.0)
        bot_contrib = min([c['contrib'] for c in contrib_stocks], default=0.0)
        if top_contrib >= 2.0:
            c_name = [c['name'] for c in contrib_stocks if c['contrib'] == top_contrib][0]
            events.append({'type': 'stock', 'text': f"{c_name} 비중 급증 (+{top_contrib:.1f}%p)"})
        elif bot_contrib <= -2.0:
            c_name = [c['name'] for c in contrib_stocks if c['contrib'] == bot_contrib][0]
            events.append({'type': 'stock', 'text': f"{c_name} 비중 급감 ({bot_contrib:.1f}%p)"})

        # 2) 업종 변화: sector_shift 중 diff >= 3.0%p
        top_sec_shift = max([s['diff'] for s in sector_shift], default=0.0) if sector_shift else 0.0
        if top_sec_shift >= 3.0:
            s_name = [s['sector'] for s in sector_shift if s['diff'] == top_sec_shift][0]
            events.append({'type': 'sector', 'text': f"{s_name} 비중 확대 (+{top_sec_shift:.1f}%p)"})

        # 3) 순위 교체: Top 10 신규 진입 종목
        new_entries = [t['name'] for t in top10_list if t['is_new']]
        if new_entries:
            events.append({'type': 'turnover', 'text': f"신규 진입: {', '.join(new_entries[:2])}"})

        # 시계열 항목 (전체 기간 1,257일)
        hist_entry = {
            'date': d,
            'concentration': conc,
            'delta': delta_conc,
            'top10_sum': float(round(top10_sum, 0)),
            'total_pos': float(round(total_pos, 0)),
            'headline': top10_list[0]['name'] if top10_list else '',
            'top1_share': top10_list[0]['share'] if top10_list else 0.0,
            'top1_name': top10_list[0]['name'] if top10_list else ''
        }
        history.append(hist_entry)

        # 주요 변곡점 판정: |delta| >= 4.0%p 또는 90분위수 이상
        if abs(delta_conc) >= 4.0:
            top_mover = max(contrib_stocks, key=lambda x: abs(x['contrib'])) if contrib_stocks else None
            mover_txt = f" {top_mover['name']} 비중 {top_mover['contrib']:+.1f}%p" if top_mover else ""
            inflections.append({
                'date': d,
                'delta': delta_conc,
                'conc': conc,
                'headline': mover_txt.strip()
            })

        # 이벤트 레인 분류 (하단 줄)
        # 1) 종목 집중: 상위 종목 중 |기여도| >= 2.5%p
        if top_contrib >= 2.5:
            c_name = [c['name'] for c in contrib_stocks if c['contrib'] == top_contrib][0]
            lane_stock.append({'date': d, 'text': f"{c_name} 비중 확대 (+{top_contrib:.1f}%p)"})
        elif bot_contrib <= -2.5:
            c_name = [c['name'] for c in contrib_stocks if c['contrib'] == bot_contrib][0]
            lane_stock.append({'date': d, 'text': f"{c_name} 비중 축소 ({bot_contrib:.1f}%p)"})

        # 2) 업종 변화: sector_shift 중 |diff| >= 3.0%p
        if sector_shift and prev_conc is not None:
            max_s = max(sector_shift, key=lambda x: abs(x['diff']))
            if abs(max_s['diff']) >= 3.0:
                s_sign = "+" if max_s['diff'] > 0 else ""
                lane_sector.append({'date': d, 'text': f"{max_s['sector']} 비중 {s_sign}{max_s['diff']:.1f}%p"})

        # 3) 순위 교체: Top 10 신규 진입 종목
        new_entries = [t['name'] for t in top10_list if t['is_new']]
        if new_entries and prev_conc is not None:
            lane_turnover.append({'date': d, 'text': f"신규 진입: {', '.join(new_entries[:2])}"})

        # 일별 상세 정보 저장:
        # 최근 150거래일(약 7개월) + 모든 변곡점 날짜에 대해 상세 보존
        is_recent = (len(valid_dates) - idx_d) <= 150
        is_major = abs(delta_conc) >= 3.5

        if is_recent or is_major:
            daily_details[d] = {
                'date': d,
                'concentration': conc,
                'delta': delta_conc,
                'top10_sum': float(round(top10_sum, 0)),
                'total_pos': float(round(total_pos, 0)),
                'summary': summary,
                'top10': top10_list,
                'contribs': contrib_stocks[:6], # 상위/하위 기여 종목 6개
                'sector_shares': sector_shares[:8], # 주요 8개 업종
                'sector_shift': sector_shift[:6] if is_recent else [],
                'stock_gainers': stock_gainers[:5] if is_recent else [],
                'stock_losers': stock_losers[:5] if is_recent else [],
                'drop_effect': drop_effect
            }

        prev_conc = conc
        prev_top10_dict = curr_top10_dict
        prev_total_pos = total_pos

    # 최종 결과 번들 구성
    latest_d = valid_dates[-1]
    latest_detail = daily_details[latest_d]

    output_payload = {
        'as_of_date': latest_d,
        'metric_name': '개미 순매수 집중도',
        'metric_name_en': 'GAEMI CONCENTRATION',
        'unit': '%',
        'window_size_days': 20,
        'latest': {
            'date': latest_d,
            'concentration': latest_detail['concentration'],
            'delta': latest_detail['delta'],
            'summary': latest_detail['summary'],
            'top10_sum': latest_detail['top10_sum'],
            'total_pos': latest_detail['total_pos'],
            'top10': latest_detail['top10'],
            'contribs': latest_detail['contribs'],
            'sector_shares': latest_detail['sector_shares'],
            'sector_shift': latest_detail['sector_shift'],
            'stock_gainers': latest_detail['stock_gainers'],
            'stock_losers': latest_detail['stock_losers'],
            'top_1d': top_1d,
            'top_5d': top_5d,
            'drop_effect': latest_detail['drop_effect']
        },
        'inflections': inflections,
        'lanes': {
            'stock': lane_stock,
            'sector': lane_sector,
            'turnover': lane_turnover
        },
        'history': history,
        'details': daily_details
    }

    print(f"[4/5] JSON 및 JS 저장: {OUTPUT_JSON}...")
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    js_code = f"window.GAEMI_CONCENTRATION = {json.dumps(output_payload, ensure_ascii=False)};\n"
    with open(OUTPUT_JS, 'w', encoding='utf-8') as f:
        f.write(js_code)

    print(f"[5/5] 완료! 소요 시간: {time.time()-t0:.2f}초")
    print(f"  최신 집중도 ({latest_d}): {latest_detail['concentration']}% ({latest_detail['delta']:+.2f}%p)")
    print(f"  요약: {latest_detail['summary']}")
    print(f"  시계열 길이: {len(history)}일")


if __name__ == '__main__':
    main()
