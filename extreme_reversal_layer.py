"""Extreme-location reversal layer.

Rejects mid-move reversals and only surfaces candidates that are at a
measurable local extreme on 15m-derived and 1h-derived structure.
No future data is used.
"""
from scanner_v2 import clamp

MIN_EXTREME_SCORE = 70.0
MAX_1H_POS_LONG = 0.30
MIN_1H_POS_SHORT = 0.70
MAX_24H_POS_LONG = 0.25
MIN_24H_POS_SHORT = 0.75
MAX_ATR_FROM_LOW = 1.0
MAX_ATR_FROM_HIGH = 1.0
MIN_MOVE_ATR = 0.75


def _score_long(f):
    if not f or f.get('data_ok') is not True: return None
    pos1=f['h1_pos_48']; pos24=f['h1_pos_24']; dist=f['dist_low_atr']; move=f['move_into_low_atr']; turn=f['turn_long']
    location=(0.45*clamp((MAX_1H_POS_LONG-pos1)/MAX_1H_POS_LONG)+0.35*clamp((MAX_24H_POS_LONG-pos24)/MAX_24H_POS_LONG)+0.20*clamp((MAX_ATR_FROM_LOW-dist)/MAX_ATR_FROM_LOW))
    return round(100*(0.70*location+0.20*clamp(move/3.0)+0.10*clamp(turn)),1)


def _score_short(f):
    if not f or f.get('data_ok') is not True: return None
    pos1=f['h1_pos_48']; pos24=f['h1_pos_24']; dist=f['dist_high_atr']; move=f['move_into_high_atr']; turn=f['turn_short']
    location=(0.45*clamp((pos1-MIN_1H_POS_SHORT)/(1-MIN_1H_POS_SHORT))+0.35*clamp((pos24-MIN_24H_POS_SHORT)/(1-MIN_24H_POS_SHORT))+0.20*clamp((MAX_ATR_FROM_HIGH-dist)/MAX_ATR_FROM_HIGH))
    return round(100*(0.70*location+0.20*clamp(move/3.0)+0.10*clamp(turn)),1)


def classify(features):
    if not features or features.get('data_ok') is not True:
        return {'status':'DATA-LIMITED','direction':'NONE','score':None,'long_score':None,'short_score':None,'blocker':'15m/1h extreme data unavailable'}
    ls=_score_long(features); ss=_score_short(features)
    long_gate=(features['h1_pos_48']<=MAX_1H_POS_LONG and features['h1_pos_24']<=MAX_24H_POS_LONG and features['dist_low_atr']<=MAX_ATR_FROM_LOW and features['move_into_low_atr']>=MIN_MOVE_ATR)
    short_gate=(features['h1_pos_48']>=MIN_1H_POS_SHORT and features['h1_pos_24']>=MIN_24H_POS_SHORT and features['dist_high_atr']<=MAX_ATR_FROM_HIGH and features['move_into_high_atr']>=MIN_MOVE_ATR)
    candidates=[]
    if long_gate and ls>=MIN_EXTREME_SCORE: candidates.append(('LONG',ls))
    if short_gate and ss>=MIN_EXTREME_SCORE: candidates.append(('SHORT',ss))
    if candidates:
        side,score=max(candidates,key=lambda x:(x[1],x[0]=='LONG'))
        return {'status':f'EXTREME REVERSAL {side}','direction':side,'score':score,'long_score':ls,'short_score':ss,'blocker':'none'}
    return {'status':'MONITOR EXTREME','direction':'NONE','score':max(ls,ss),'long_score':ls,'short_score':ss,'blocker':'extreme gate not met'}
