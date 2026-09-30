import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

POSTS = Path('posts.json')
STATE = Path('state.json')
TOKEN = os.environ.get('BOT_TOKEN', '')
TARGET = os.environ.get('TARGET_CHAT', '')
SOURCE = os.environ.get('SOURCE_CHAT', TARGET)


def api(method, payload):
    request = urllib.request.Request(
        f'https://api.telegram.org/bot{TOKEN}/{method}',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'{method}: HTTP {exc.code}: {exc.read().decode("utf-8", "replace")}') from exc
    if not result.get('ok'):
        raise RuntimeError(f'{method}: {result.get("description", result)}')
    return result['result']


def publish(post):
    if isinstance(post, int):
        post = {'message_id': post}
    if not isinstance(post, dict):
        raise ValueError('帖子须为数字消息 ID 或对象')
    # 支持手写格式：{"id": 1, "text": "配文", "media": ["https://t.me/channel/123"]}
    if 'media' in post:
        urls = post['media']
        if not isinstance(urls, list) or not urls:
            raise ValueError('media 须为非空链接数组')
        parsed = []
        for url in urls:
            match = re.fullmatch(r'https://t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/(\d+)(?:\?single)?', url)
            if not match:
                raise ValueError(f'无效的 t.me 消息链接：{url}')
            parsed.append((f'@{match.group(1)}', int(match.group(2))))
        channels = {channel.lower() for channel, _ in parsed}
        if len(channels) != 1:
            raise ValueError('同一帖子的 media 必须来自同一个频道')
        source = parsed[0][0]
        ids = [number for _, number in parsed]
        caption = post.get('text', '')
        if not isinstance(caption, str) or len(caption) > 1024:
            raise ValueError('图文配文 text 必须是字符串且不超过 1024 字符')
        if len(ids) == 1:
            payload = {'chat_id': TARGET, 'from_chat_id': source, 'message_id': ids[0]}
            if caption:
                payload['caption'] = caption
            api('copyMessage', payload)
        else:
            result = api('copyMessages', {'chat_id': TARGET, 'from_chat_id': source, 'message_ids': ids})
            if len(result) != len(ids):
                raise RuntimeError('复制消息数量不足，请检查机器人能否访问全部原帖')
            if caption:
                try:
                    api('editMessageCaption', {'chat_id': TARGET, 'message_id': result[0]['message_id'], 'caption': caption})
                except RuntimeError as exc:
                    print(f'相册已复制，但修改配文失败：{exc}', file=sys.stderr)
        return
    if 'message_ids' in post:
        ids = post['message_ids']
        if not isinstance(ids, list) or not 2 <= len(ids) <= 100 or not all(type(x) is int and x > 0 for x in ids):
            raise ValueError('message_ids 须为 2–100 个正整数消息 ID')
        result = api('copyMessages', {'chat_id': TARGET, 'from_chat_id': SOURCE, 'message_ids': ids})
        if len(result) != len(ids):
            raise RuntimeError('相册复制数量不足，请检查机器人是否有权访问全部消息')
    elif 'message_id' in post:
        api('copyMessage', {'chat_id': TARGET, 'from_chat_id': SOURCE, 'message_id': post['message_id']})
    elif 'text' in post:
        api('sendMessage', {'chat_id': TARGET, 'text': post['text']})
    elif 'photo' in post or 'video' in post:
        kind = 'photo' if 'photo' in post else 'video'
        payload = {'chat_id': TARGET, kind: post[kind]}
        if 'caption' in post:
            payload['caption'] = post['caption']
        api('sendPhoto' if kind == 'photo' else 'sendVideo', payload)
    else:
        raise ValueError('帖子缺少 media、message_id、message_ids、text、photo 或 video')


def save(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


# 北京时间：每天十个固定时间，每次发布一条。
POST_TIMES = ['08:00', '09:30', '11:00', '12:30', '14:00',
              '15:30', '17:00', '18:30', '20:00', '21:30']
TIMEZONE = ZoneInfo('Asia/Shanghai')


def main():
    if not TOKEN or not TARGET:
        raise ValueError('请设置 BOT_TOKEN 和 TARGET_CHAT')
    posts = json.loads(POSTS.read_text(encoding='utf-8'))
    if not isinstance(posts, list) or not posts:
        raise ValueError('posts.json 须为非空数组')
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'index': 0, 'date': '', 'sent_today': 0}
    now = datetime.now(TIMEZONE)
    today = now.date().isoformat()
    if state.get('date') != today:
        state['date'], state['sent_today'] = today, 0
    state.pop('schedule', None)
    save(state)
    due = sum(t <= now.strftime('%H:%M') for t in POST_TIMES)
    while state['sent_today'] < due:
        if datetime.now(TIMEZONE).date().isoformat() != today:
            break
        index = state['index'] % len(posts)
        print(f'发布第 {index + 1}/{len(posts)} 条', flush=True)
        publish(posts[index])
        state['index'] = (index + 1) % len(posts)
        state['sent_today'] += 1
        save(state)
    print(f'{today} 已发布 {state["sent_today"]}/10 条；下一条位置：{state["index"] + 1}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'错误：{exc}', file=sys.stderr)
        sys.exit(1)
