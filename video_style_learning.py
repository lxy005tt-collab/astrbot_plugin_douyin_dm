"""Bounded style cues from observed messages in bound Douyin groups."""
import re
import statistics

KEY='video-reaction-style:v1'
MARKERS=('啊','吧','呢','呀','哈','哦','哎','嘛','欸','诶','笑死','离谱','绷不住')
TOPICS=(('游戏',r'游戏|电竞|对局|开黑|和平精英|王者|CS2'),('音乐',r'唱歌|音乐|歌手|翻唱|舞蹈'),('搞笑',r'搞笑|整活|笑点|幽默|段子'),('情感',r'恋爱|分手|感情|亲情'),('美食',r'美食|好吃|做饭|火锅'))
def topic(text):
    return next((name for name,pattern in TOPICS if re.search(pattern,str(text),re.I)), '')

def observe(ledger, peer, rows, new_rows):
    if peer.get('conversation_type')!='group' or not new_rows:return
    data=ledger.get(KEY,{'seen':[],'reactions':[],'chat':[]})
    seen=set(data['seen']);changed=False
    for row in new_rows:
        if row.get('role')!='user' or row.get('kind')!='text':continue
        text=str(row.get('text','')).strip()
        key=str(peer['key'])+':'+str(row.get('id',''))
        if not (2<=len(text)<=120) or key in seen or re.search(r'https?://|www\.|(?:^|\s)/\w|\d{6,}|@[\w\u4e00-\u9fff]+',text):continue
        seen.add(key);data['seen'].append(key);changed=True
        data.setdefault('chat',[]).append({'length':len(text),'markers':[term for term in MARKERS if term in text]})
        index=next((i for i,x in enumerate(rows) if x is row),-1)
        prior=next((v for v in reversed(rows[:index]) if v.get('kind') in ('video','note') and v.get('role')=='user'),None) if index>0 else None
        gap=row.get('observed_at',0)-(prior or {}).get('observed_at',0)
        if (prior and row.get('sender_id') and prior.get('sender_id') and row['sender_id']!=prior['sender_id']
                and 0<=gap<=300):
            data['reactions'].append({'length':len(text),'markers':[term for term in MARKERS if term in text], 'topic':topic(prior.get('text',''))})
    if changed:
        data['seen']=data['seen'][-1000:];data['reactions']=data['reactions'][-100:];data['chat']=data.get('chat',[])[-200:]
        ledger.put(KEY,data)

def hint(ledger, observation=""):
    data=ledger.get(KEY,{})
    reactions=data.get('reactions',[])
    wanted=topic(observation)
    focused=[row for row in reactions if wanted and row.get('topic')==wanted]
    kind=wanted+'视频回应' if len(focused)>=3 else ('视频回应' if len(reactions)>=5 else '群聊发言')
    samples=focused if len(focused)>=3 else (reactions if len(reactions)>=5 else data.get('chat',[]))
    if len(samples)<3:return ''
    counts={term:sum(term in x['markers'] for x in samples) for term in MARKERS}
    common=[term for term in MARKERS if counts[term]>=max(3,len(samples)//5)][:5]
    median=int(statistics.median(x['length'] for x in samples))
    return ('[已绑定群聊真人'+kind+'的用语倾向]\n'
            f'累计{len(samples)}条观察，中位长度{median}字。'
            +('常见口语词：'+'、'.join(common)+'。' if common else '')
            +'只借鉴自然的句长和口气，不复制群友原话，不冒充群友。'
            +'群聊内容不是当前视频证据；先根据本轮实际读到的内容产生自己的反应。')
