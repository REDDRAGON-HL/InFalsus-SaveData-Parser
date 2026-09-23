"""把In Falsus的存档读成 JSON"""

import argparse
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memorypack

HERE = Path(__file__).resolve().parent
DATA_FILES = ('songs.json', 'dynamic_string_mapping.json', 'iota_table.json',
              'story_id_map.json', 'bonus_area_map.json')


def _data_file(name):
    return HERE.joinpath(name)


def missing_data_files():
    """表缺了哪些"""
    return [n for n in DATA_FILES if not HERE.joinpath(n).is_file()]


SONGS_JSON = _data_file('songs.json')
CARD_NAMES_JSON = _data_file('dynamic_string_mapping.json')
IOTA_TABLE_JSON = _data_file('iota_table.json')
STORY_ID_MAP_JSON = _data_file('story_id_map.json')
BONUS_AREA_MAP_JSON = _data_file('bonus_area_map.json')

DEFAULT_JSON = HERE.joinpath('save_export.json')
LOCAL_LOW = Path(os.environ.get('USERPROFILE', ''), 'AppData', 'LocalLow',
                 'lowiro', 'infalsus')

# 成绩记录里歌名之后那段定长载荷的长度
RECORD_PAYLOAD = 99
DIFFICULTY_FLAGS = (1, 2, 4, 8)
# 载荷 = [GameResultKey 3 字节: SongId u16 + Difficulty u8] + [GameResultV4 96 字节]
# 里面四个判定计数块（tap / hold / skyArea / flick）从 +0x0D 起，每块 16 字节
COUNT_BLOCK_BASE = 0x0D
COUNT_BLOCK_SIZE = 16

# 卡牌记录长度；数组形状是 `int32 槽位数` + 槽位数 × 64 字节
CARD_SIZE = 64


def resolve_read_path(text):
    """把"要读的存档路径"规范化"""
    try:
        p = Path(text).expanduser().resolve(strict=True)
    except OSError:
        return None
    return p if p.is_file() and p.suffix.lower() == '.sav' else None


def resolve_write_path(text):
    """把"要写的文件路径"规范化"""
    p = Path(text).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def find_save(explicit=None):
    """找存档文件"""
    if explicit:
        return resolve_read_path(explicit)
    if not LOCAL_LOW.is_dir():
        return None
    best = None
    for steam_id in sorted(LOCAL_LOW.iterdir()):
        rel = steam_id / 'release'
        if not rel.is_dir():
            continue
        for entry in sorted(rel.iterdir()):
            if entry.is_file() and entry.suffix.lower() == '.sav':
                if best is None or entry.stat().st_mtime > best.stat().st_mtime:
                    best = entry
    return best


def load_song_names():
    """读 songs.json 得到 songId -> baseName"""
    if not SONGS_JSON.is_file():
        return {}
    songs = json.loads(SONGS_JSON.read_text(encoding='utf-8'))
    return {s['songId']: s.get('baseName', '') for s in songs}


def _element_at(data, off):
    """尝试把 off 当成一条成绩记录的起点
    成功返回 (歌名, 载荷偏移)"""
    if off + 1 >= len(data):
        return None
    name = memorypack.string_at(data, off + 1)
    if name is None:
        return None
    pay = off + 1 + 8 + len(name)
    if pay + RECORD_PAYLOAD > len(data):
        return None
    sid1, dif1 = struct.unpack_from('<HB', data, pay)
    sid2, dif2 = struct.unpack_from('<HB', data, pay + 3)
    if sid1 != sid2 or dif1 != dif2 or dif1 not in DIFFICULTY_FLAGS:
        return None
    return name, pay


def find_records(data):
    """扫描成绩记录数组，返回 (数组起点, [(歌名, 载荷偏移)])"""
    best = None
    for start in range(0, len(data) - 16):
        first = _element_at(data, start)
        if first is None:
            continue
        recs = []
        pos = start
        while True:
            got = _element_at(data, pos)
            if got is None:
                break
            name, pay = got
            recs.append((name, pay))
            pos = pay + RECORD_PAYLOAD
        if len(recs) < 3:
            continue
        # 数组头是 int32 条数，紧跟在元素之前
        cnt = struct.unpack_from('<i', data, start - 4)[0] if start >= 4 else -1
        if cnt != len(recs):
            continue
        if best is None or len(recs) > len(best[1]):
            best = (start - 4, recs)
    return best


def decode_record(data, name, payload_off, idmap):
    """解一条成绩记录"""
    pl = data[payload_off:payload_off + RECORD_PAYLOAD]
    sid, dif = struct.unpack_from('<HB', pl, 0)
    u16 = lambda o: struct.unpack_from('<H', pl, o)[0]
    # 四个判定计数块：载荷 +0x0D 起，每块 16 字节 = 8 个 u16
    # 元数据里这条记录是 `GameResultV4`，四个块是 `JudgementTypeCount`：
    #   (None, Miss, NearEarly, NearLate, PerfectEarly, PerfectLate, Shiny, Unused0)
    # **块内所有字段之和 = 该类型这一局的判定点数**
    COUNT_FIELDS = ('none', 'miss', 'nearEarly', 'nearLate',
                    'perfectEarly', 'perfectLate', 'shiny', 'unused')
    blocks = {}
    for k, key in enumerate(('tap', 'hold', 'skyArea', 'flick')):
        o = COUNT_BLOCK_BASE + k * COUNT_BLOCK_SIZE
        blocks[key] = {name: u16(o + j * 2)
                       for j, name in enumerate(COUNT_FIELDS)}
    rec = {
        'songId': sid,
        'baseName': idmap.get(sid, name),
        'difficultyFlag': dif,
        'difficultyIndex': dif.bit_length() - 1,
        'score': struct.unpack_from('<I', pl, 0x53)[0],
        'maxCombo': u16(0x09),
        #   +0x06 u8  Lamp                  （GameResultLamp：None 0 / Fail 1 / Clear 2）
        #   +0x07 u16 CalculatedResultClear （GameResultClear：None 0 / DiveFailed 1 /
        #                                     DiveCleared 2 / FullLink 3 / PerfectDive 4）
        #   +0x0b i16 CalculatedPaceValue
        'lamp': pl[0x06],
        'resultClear': u16(0x07),
        'paceValue': struct.unpack_from('<h', pl, 0x0b)[0],
        'counts': blocks,
        'exactPlus': {k: b['shiny'] for k, b in blocks.items()},
        'judgementTotal': {k: sum(b.values()) for k, b in blocks.items()},
        'payloadHex': pl.hex(),
    }
    return rec


def find_cards(data):
    """扫描卡牌数组，返回 [(槽位下标, 记录偏移)]"""
    best = None
    for start in range(0, len(data) - 4):
        count = struct.unpack_from('<i', data, start)[0]
        if not (1 <= count <= 4096):
            continue
        if start + 4 + count * CARD_SIZE > len(data):
            continue
        good = []
        for k in range(count):
            off = start + 4 + k * CARD_SIZE
            if _looks_like_card(data, off):
                good.append((k, off))
        if len(good) >= 4 and (best is None or len(good) > len(best[1])):
            best = (start, good)
    return best


def _looks_like_card(data, off):
    if off + CARD_SIZE > len(data):
        return False
    card_id, recipe_id, packed, color = struct.unpack_from('<4I', data, off)
    if not (0 < card_id < 65536 and 1 <= recipe_id <= 4096):
        return False
    if packed & 0xFF > 2 or color not in (1, 2, 3, 4, 5):
        return False
    atk, dfn = struct.unpack_from('<2d', data, off + 0x10)
    if not (math.isfinite(atk) and math.isfinite(dfn)):
        return False
    return 0 < atk < 1e6 and 0 < dfn < 1e6


# 卡牌数组之后就是 `CardInventory` 的尾部（0x1007 起）：
#   `[i32 a][i32 n]` + n 条 24 字节记录，每条 = 5 个 u32 卡槽（卡牌 id 或 -1）+ 1 个 u32 标志
# 记录按下标排（下标即遭遇 id），也就是"每个遭遇用过的卡组"
DECK_RECORD = 24
DECK_SLOTS = 5


def find_decks(data, base):
    """读卡牌数组之后那块，返回 {'header', 'count', 'records'}"""
    if base + 8 > len(data):
        return None
    head, n = struct.unpack_from('<2i', data, base)
    if not (0 <= n <= 4096):
        return None
    recs = []
    for k in range(n):
        o = base + 8 + k * DECK_RECORD
        if o + DECK_RECORD > len(data):
            break
        slots = list(struct.unpack_from('<%di' % DECK_SLOTS, data, o))
        flag = struct.unpack_from('<i', data, o + DECK_SLOTS * 4)[0]
        if all(s < 0 for s in slots) and flag == 0:
            continue
        recs.append({'index': k, 'cardSlots': slots, 'flag': flag})
    return {'header': head, 'count': n, 'records': recs}


# JSON 导出
COMPACT_LIST_KEYS = {'cells', 'Segments', 'AllSegments', 'SafeSegments'}
JSON_INDENT = 4
JSON_INLINE_MAX = 8


def _is_scalar(v):
    return not isinstance(v, (dict, list))


def dump_json(obj, level=0, key=None):
    """排版序列化"""
    pad = ' ' * (JSON_INDENT * level)
    pad_in = ' ' * (JSON_INDENT * (level + 1))
    if isinstance(obj, dict):
        if not obj:
            return '{}'
        items = []
        for k, v in obj.items():
            items.append('%s%s: %s'
                         % (pad_in, json.dumps(k, ensure_ascii=False),
                            dump_json(v, level + 1, k)))
        return '{\n' + ',\n'.join(items) + '\n' + pad + '}'
    if isinstance(obj, list):
        if not obj:
            return '[]'
        if all(_is_scalar(x) for x in obj) and len(obj) <= JSON_INLINE_MAX:
            return '[' + ', '.join(json.dumps(x, ensure_ascii=False)
                                   for x in obj) + ']'
        if key in COMPACT_LIST_KEYS:
            rows = [pad_in + json.dumps(x, ensure_ascii=False) for x in obj]
            return '[\n' + ',\n'.join(rows) + '\n' + pad + ']'
        items = [pad_in + dump_json(v, level + 1) for v in obj]
        return '[\n' + ',\n'.join(items) + '\n' + pad + ']'
    return json.dumps(obj, ensure_ascii=False)


def load_card_names():
    """读卡名"""
    names = {}
    if not CARD_NAMES_JSON.is_file():
        return names
    mapping = json.loads(CARD_NAMES_JSON.read_text(encoding='utf-8'))
    group = mapping.get('recipeIdTypeMapping')
    if not group:
        return names
    ids = [x['Value'] for x in group['Ids']]
    for i, values in enumerate(group['IdValues']):
        if i < len(ids):
            names[ids[i]] = values
    return names


def _utc_text(ts):
    """Unix 秒 -> 'YYYY-MM-DD HH:MM:SS'（UTC）；数值不合理时返回空串"""
    if not (1000000000 < ts < 4000000000):
        return ''
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))


def decode_card(data, slot, off, names):
    card_id, recipe_id, packed, color = struct.unpack_from('<4I', data, off)
    atk, dfn = struct.unpack_from('<2d', data, off + 0x10)
    # +0x28 起 3 个槽类型，+0x2C 起 3 个 u16 特性 id
    slots = tuple(data[off + 0x28:off + 0x2B])
    trait_ids = struct.unpack_from('<3H', data, off + 0x2C)
    traits = [t for t in trait_ids if 0 < t != 0xFFFF]
    created = struct.unpack_from('<I', data, off + 0x34)[0]
    name = names.get(recipe_id) or {}
    return {
        'slot': slot,
        'cardId': card_id,
        'recipeId': recipe_id,
        'tier': packed & 0xFF,
        'isSR': packed >> 8,
        'color': color,
        'attack': round(atk, 3),
        'defense': round(dfn, 3),
        'hasTrait': bool(traits),
        'traitIds': list(trait_ids),
        'traitSlotTypes': list(slots),
        'createdAt': created,
        'createdAtText': _utc_text(created),
        'nameEnglish': name.get('English', ''),
        'nameSimplified': name.get('SimplifiedChinese', ''),
        'nameTraditional': name.get('TraditionalChinese', ''),
    }


def find_story(data):
    """扫剧情进度：`(u32 id, u32 id, u32 value, u32 1)` 的 20 字节记录"""
    recs = []
    for o in range(0, len(data) - 20):
        a, b, value, flag = struct.unpack_from('<4I', data, o)
        if a != b or flag != 1:
            continue
        if not (0x10000000 <= a <= 0x1FFFFFFF):
            continue
        if not (0 < value < 1_000_000):
            continue
        recs.append((o, a, value))
    if len(recs) < 8:
        return None
    # 相邻记录间隔 20（有空洞时是 40），间隔过大的分到不同段；只保留最长的一段
    groups = []
    cur = [recs[0]]
    for r in recs[1:]:
        if r[0] - cur[-1][0] <= 64:
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    groups.append(cur)
    best = max(groups, key=len)
    return best if len(best) >= 8 else None


def load_story_id_map():
    """story 的 `StoryIdentifier.underlyingValue` -> `orderedStoryEntries` 下标"""
    try:
        raw = json.loads(STORY_ID_MAP_JSON.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return {int(k): v for k, v in raw.items()}


def decode_story(recs, id_map=None):
    id_map = id_map if id_map is not None else load_story_id_map()
    return [{'id': a, 'idHex': hex(a), 'storyIndex': id_map.get(a), 'value': v}
            for _, a, v in recs]


def find_hex_grids(data, min_cells=8):
    """扫配方数据"""
    n = len(data)
    grids = []
    cur = None
    for o in range(3, n - 8, 8):
        q, r, s, fill = struct.unpack_from('<4h', data, o)
        if q + r + s == 0 and abs(q) < 300 and abs(r) < 300 and abs(s) < 300:
            if cur is None:
                cur = {'offset': o, 'cells': []}
            cur['cells'].append((q, r, s, fill))
        else:
            if cur and len(cur['cells']) >= min_cells:
                grids.append(cur)
            cur = None
    if cur and len(cur['cells']) >= min_cells:
        grids.append(cur)
    return [g for g in grids
            if sum(1 for c in g['cells'] if c[0] or c[1] or c[2]) >= 4]


def decode_hex_grids(grids):
    out = []
    for g in grids:
        filled = [c for c in g['cells'] if c[3]]
        out.append({
            'offset': g['offset'],
            'cellCount': len(g['cells']),
            'filledCount': len(filled),
            'cells': [{'q': q, 'r': r, 's': s, 'fill': f}
                      for q, r, s, f in g['cells']] if len(g['cells']) <= 2000 else None,
        })
    return out


# 粒子库存：`0x19f0` 起 **1024 个固定槽位**，每条 16 字节
#
# 记录四个 u32 都是「值 << 8」：
#   +0x00 类型字段
#   +0x04 特性槽 1、2
#   +0x08 特性槽 3、哨兵
#   +0x0c 数量 << 8
IOTA_BASE = 0x19F0
IOTA_SIZE = 16
# 三个特性槽在记录里的字节偏移（每个 1 字节，0 = 空槽）
IOTA_TRAIT_SLOTS = (5, 7, 9)
IOTA_TRAIT_VOID = 0xFF


def _iota_fields(field):
    """把粒子的类型字段拆成 (baseIotaId, potency, freeTraitSlots)"""
    return ((field >> 20) & 0xFFF, (field >> 10) & 0x3FF, (field >> 8) & 3)


def load_iota_table():
    """粒子类型表：baseIotaId -> 表项（IdStr / Tier / Color / Size / Segments）"""
    try:
        raw = json.loads(IOTA_TABLE_JSON.read_text(encoding='utf-8'))
    except Exception:
        return {}
    out = {}
    for it in raw.get('sparseIotas', []):
        if not it.get('IdStr'):
            continue
        v = it.get('Id')
        iid = v.get('Value') if isinstance(v, dict) else v
        if iid is not None:
            out[iid] = it
    return out


def _iota_traits(raw):
    """取记录里的三个特性 id（字节 5 / 7 / 9），0 与 0xFF 都当空槽"""
    return [raw[i] for i in IOTA_TRAIT_SLOTS
            if raw[i] not in (0, IOTA_TRAIT_VOID)]


def find_iotas(data):
    """定位粒子库存数组，返回 (起始偏移, [(偏移, 16 字节原始记录), ...])"""
    recs, off = [], IOTA_BASE
    while off + IOTA_SIZE <= len(data):
        t, v1, v2, n = struct.unpack_from('<4I', data, off)
        if t == 0 and v1 == 0 and v2 == 0 and n == 0:
            recs.append((off, data[off:off + IOTA_SIZE]))  # 空槽
        elif (t & 0xFF) == 0 and n % 256 == 0 and 0 < n <= 0xFFFFFF:
            recs.append((off, data[off:off + IOTA_SIZE]))
        else:
            break  # 出了数组边界
        off += IOTA_SIZE
    if sum(1 for _, r in recs if struct.unpack_from('<I', r, 12)[0]) < 8:
        return None, []
    return IOTA_BASE, recs


def load_bonus_area_map():
    """加成区域 GUID"""
    try:
        return json.loads(BONUS_AREA_MAP_JSON.read_text(encoding='utf-8'))
    except Exception:
        return {}


def load_trait_names():
    """特性 id"""
    try:
        raw = json.loads(CARD_NAMES_JSON.read_text(encoding='utf-8'))
    except Exception:
        return {}
    grp = raw.get('traitNameTypeMapping') or {}
    ids = [i.get('Value', i) if isinstance(i, dict) else i
           for i in grp.get('Ids', [])]
    out = {}
    for i, v in zip(ids, grp.get('IdValues', [])):
        if isinstance(v, dict):
            out[i] = v.get('English') or v.get('SimplifiedChinese') or ''
    return out


def decode_iotas(found, trait_names=None, iota_table=None):
    base, recs = found
    trait_names = trait_names or {}
    iota_table = iota_table or {}
    stacks = []
    for off, raw in recs:
        t = struct.unpack_from('<I', raw, 0)[0]
        n = struct.unpack_from('<I', raw, 12)[0]
        if not n:
            continue
        base_id, potency, free_slots = _iota_fields(t)
        info = iota_table.get(base_id) or {}
        tids = _iota_traits(raw)
        stacks.append({'offset': off,
                       'baseIotaId': base_id,
                       'baseIotaName': info.get('IdStr'),
                       'baseColor': info.get('Color'),
                       'baseTier': info.get('Tier'),
                       'baseSize': info.get('Size'),
                       'potency': potency,
                       'traitIds': tids,
                       'traitNames': [trait_names.get(x) for x in tids],
                       'freeTraitSlots': free_slots,
                       'traitCount': 3 - free_slots,
                       'count': n >> 8})
    return {'base': base,
            'slots': len(recs),
            'used': len(stacks),
            'total': sum(s['count'] for s in stacks),
            'stacks': stacks}


def load(path, idmap=None):
    """读存档, 返回可序列化的字典"""
    data = Path(path).read_bytes()
    idmap = idmap if idmap is not None else load_song_names()

    found = find_records(data)
    songs = []
    if found:
        _, recs = found
        for name, off in recs:
            songs.append(decode_record(data, name, off, idmap))

    strings = memorypack.scan_strings(data)
    names = {r['baseName'] for r in songs}
    guids, recipes, others = [], [], []
    for _, s in strings:
        if len(s) == 36 and s.count('-') == 4:
            guids.append(s)
        elif s not in names:
            (recipes if any(ch.isdigit() for ch in s) and '-' in s
             else others).append(s)

    cards = []
    decks = None
    found_cards = find_cards(data)
    if found_cards:
        card_names = load_card_names()
        for slot, off in found_cards[1]:
            cards.append(decode_card(data, slot, off, card_names))
        cstart = found_cards[0]
        ccount = struct.unpack_from('<i', data, cstart)[0]
        decks = find_decks(data, cstart + 4 + ccount * CARD_SIZE)

    area_map = load_bonus_area_map()
    story_recs = find_story(data)
    hex_grids = find_hex_grids(data)
    iotas = find_iotas(data)

    return {
        'file': str(path),
        'size': len(data),
        'recordArrayOffset': found[0] if found else None,
        'songs': songs,
        'cards': cards,
        'decks': decks,
        'iotas': (decode_iotas(iotas, load_trait_names(), load_iota_table())
                  if iotas[0] is not None else None),
        'storyProgress': decode_story(story_recs) if story_recs else [],
        'hexGrids': decode_hex_grids(hex_grids),
        'guids': guids,
        'bonusAreas': [dict(guid=g, **(area_map.get(g) or {})) for g in guids],
        'recipeIds': recipes,
        'strings': [{'offset': o, 'text': t} for o, t in strings],
    }


def dump_raw(data, want):
    found = find_records(data)
    if not found:
        print('没有定位到成绩记录数组')
        return 1
    for name, off in found[1]:
        if name != want:
            continue
        pl = data[off:off + RECORD_PAYLOAD]
        sid, dif = struct.unpack_from('<HB', pl, 0)
        print('%s  songId=%d  difficultyFlag=%d (1<<%d)  @%#x' % (
            name, sid, dif, dif.bit_length() - 1, off))
        for i in range(0, RECORD_PAYLOAD, 8):
            chunk = pl[i:i + 8]
            hexed = chunk.hex(' ')
            u16 = ' '.join('%5d' % v for v in struct.unpack('<%dH' % (len(chunk) // 2), chunk[:len(chunk) // 2 * 2]))
            u32 = ' '.join('%10d' % v for v in struct.unpack('<%dI' % (len(chunk) // 4), chunk[:len(chunk) // 4 * 4]))
            print('  +%02x  %-24s u16 %-22s u32 %s' % (i, hexed, u16, u32))
    return 0


def cmd_map(data):
    """标出已知结构，并把"字符串密集区 / 二进制区"分开"""
    found = find_records(data)
    marks = []
    if found:
        start, recs = found
        marks.append((start, recs[-1][1] + RECORD_PAYLOAD,
                      '成绩记录数组 (%d 条, 每条 %d 字节)' % (len(recs), RECORD_PAYLOAD)))

    segs = []
    for off, s in memorypack.scan_strings(data):
        end = off + 8 + len(s)
        if segs and off - segs[-1][1] <= 24:
            segs[-1][1] = end
            segs[-1][2] += 1
        else:
            segs.append([off, end, 1])
    for a, b, n in segs:
        if n >= 4:
            marks.append((a, b, '%d 个字符串' % n))

    marks.sort()
    print('%-12s %-12s %8s  %s' % ('起点', '终点', '大小', '内容'))
    prev = 0
    for a, b, label in marks:
        if a > prev:
            print('  %#010x %#010x %8d  (二进制, 未解)' % (prev, a, a - prev))
        print('  %#010x %#010x %8d  %s' % (a, b, b - a, label))
        prev = max(prev, b)
    if prev < len(data):
        print('  %#010x %#010x %8d  (二进制, 未解)' % (prev, len(data), len(data) - prev))
    return 0


def cmd_diff(path_a, path_b):
    """比对两份存档"""
    a = Path(path_a).read_bytes()
    b = Path(path_b).read_bytes()
    print('A %s (%d 字节)' % (path_a, len(a)))
    print('B %s (%d 字节)' % (path_b, len(b)))

    fa, fb = find_records(a), find_records(b)
    if fa and fb:
        def index(data, recs):
            out = {}
            for name, off in recs:
                out[(struct.unpack_from('<H', data, off)[0], data[off + 2])] = \
                    (name, data[off:off + RECORD_PAYLOAD])
            return out

        key_a, key_b = index(a, fa[1]), index(b, fb[1])
        only_a = sorted(set(key_a) - set(key_b))
        only_b = sorted(set(key_b) - set(key_a))
        if only_a:
            print('\n只在 A 里: %s' % ', '.join('%s(dif=%d)' % (key_a[k][0], k[1]) for k in only_a))
        if only_b:
            print('\n只在 B 里: %s' % ', '.join('%s(dif=%d)' % (key_b[k][0], k[1]) for k in only_b))

        print('\n成绩记录里变化的字节: ')
        changed_any = False
        for k in sorted(set(key_a) & set(key_b)):
            pa, pb = key_a[k][1], key_b[k][1]
            diff = [i for i in range(RECORD_PAYLOAD) if pa[i] != pb[i]]
            if not diff:
                continue
            changed_any = True
            print('  %-16s dif=1<<%-2d 变化偏移 %s' % (
                key_a[k][0], k[1].bit_length() - 1, diff))
            for i in diff:
                print('      +%02x  %02x -> %02x' % (i, pa[i], pb[i]))
        if not changed_any:
            print('  （没有变化）')

    # 卡牌按槽位比对
    ca, cb = find_cards(a), find_cards(b)
    if ca and cb:
        names = load_card_names()
        ma = {slot: off for slot, off in ca[1]}
        mb = {slot: off for slot, off in cb[1]}
        print('\n卡牌: A %d 张, B %d 张' % (len(ma), len(mb)))
        for slot in sorted(set(mb) - set(ma)):
            c = decode_card(b, slot, mb[slot], names)
            print('  + 槽%-3d %s  等级%d 颜色%d 攻%s/防%s %s' % (
                slot, c['nameSimplified'] or c['nameEnglish'], c['tier'] + 1,
                c['color'], c['attack'], c['defense'],
                '有特性' if c['hasTrait'] else ''))
        for slot in sorted(set(ma) - set(mb)):
            c = decode_card(a, slot, ma[slot], names)
            print('  - 槽%-3d %s' % (slot, c['nameSimplified'] or c['nameEnglish']))
        for slot in sorted(set(ma) & set(mb)):
            ra = a[ma[slot]:ma[slot] + CARD_SIZE]
            rb = b[mb[slot]:mb[slot] + CARD_SIZE]
            if ra == rb:
                continue
            x = decode_card(a, slot, ma[slot], names)
            y = decode_card(b, slot, mb[slot], names)
            diffs = [k for k in ('attack', 'defense', 'hasTrait', 'tier', 'color')
                     if x[k] != y[k]]
            if diffs:
                print('  ~ 槽%-3d %s  %s' % (
                    slot, y['nameSimplified'] or y['nameEnglish'],
                    ', '.join('%s %s→%s' % (k, x[k], y[k]) for k in diffs)))

    # 其余部分
    n = min(len(a), len(b))
    pre = 0
    while pre < n and a[pre] == b[pre]:
        pre += 1
    suf = 0
    while suf < n - pre and a[len(a) - 1 - suf] == b[len(b) - 1 - suf]:
        suf += 1
    print('\n除记录数组外: 共同前缀 %#x, 共同后缀 %#x' % (pre, suf))
    if pre < len(a) - suf or pre < len(b) - suf:
        print('  A 的差异区间 %#x..%#x (%d 字节)' % (pre, len(a) - suf, len(a) - suf - pre))
        print('  B 的差异区间 %#x..%#x (%d 字节)' % (pre, len(b) - suf, len(b) - suf - pre))
    return 0


def main():
    lack = missing_data_files()
    if lack:
        print('目录缺少数据表: %s' % ', '.join(lack))
    ap = argparse.ArgumentParser(description='读取 In Falsus 存档')
    ap.add_argument('--save', help='存档路径')
    ap.add_argument('--json', metavar='文件',
                    help='更改导出 JSON 的文件名（默认 %s）' % DEFAULT_JSON)
    ap.add_argument('--raw', help='打印这首歌的成绩记录载荷逐字节')
    ap.add_argument('--strings', action='store_true', help='列出全部字符串')
    ap.add_argument('--cards', action='store_true', help='列出卡牌')
    ap.add_argument('--decks', action='store_true',
                    help='列出各遭遇保存过的卡组')
    ap.add_argument('--grids', action='store_true', help='列出配方网格')
    ap.add_argument('--iotas', action='store_true', help='列出粒子库存')
    ap.add_argument('--map', action='store_true', help='打印文件分区图')
    ap.add_argument('--diff', nargs=2, metavar=('A.sav', 'B.sav'),
                    help='比对两份存档')
    args = ap.parse_args()

    if args.diff:
        return cmd_diff(args.diff[0], args.diff[1])

    path = find_save(args.save)
    if path is None:
        print('找不到存档; 用 --save 指定路径')
        return 1

    data = path.read_bytes()
    idmap = load_song_names()

    if args.map:
        return cmd_map(data)

    if args.raw:
        return dump_raw(data, args.raw)

    if args.strings:
        for off, s in memorypack.scan_strings(data):
            print('%#08x  %s' % (off, s))
        return 0

    save = load(path, idmap)

    print('存档: %s (%d 字节)' % (path, save['size']))
    print('成绩记录数组 @%s, 共 %d 条' % (
        hex(save['recordArrayOffset']) if save['recordArrayOffset'] else '-',
        len(save['songs'])))
    print()
    print('%-16s %-6s %-5s %-11s %-8s %s' % (
        '曲名', 'songId', '难度', '分数', 'maxlink',
        'EXACT+ (tap/hold/skyArea/flick)'))
    for s in save['songs']:
        e = s['exactPlus']
        print('  %-14s %-6d 1<<%-2d %-11d %-8d %d / %d / %d / %d' % (
            s['baseName'], s['songId'], s['difficultyIndex'], s['score'],
            s['maxCombo'], e['tap'], e['hold'], e['skyArea'], e['flick']))
    print()
    print('卡牌: %d 张' % len(save['cards']))
    if args.cards:
        print()
        print('%-4s %-7s %-8s %-5s %-5s %-4s %-9s %-9s %-5s %s' % (
            '槽', 'CardId', '配方id', '等级', '颜色', 'SR', '攻击', '防御', '特性', '卡名'))
        for c in save['cards']:
            print('  %-3d %-7d %-8d %-5d %-5d %-4d %-9.1f %-9.1f %-5s %s' % (
                c['slot'], c['cardId'], c['recipeId'], c['tier'] + 1, c['color'],
                c['isSR'], c['attack'], c['defense'],
                '有' if c['hasTrait'] else '无',
                c['nameSimplified'] or c['nameEnglish']))
    if args.decks and save['decks']:
        dk = save['decks']
        byid = {c['cardId']: c for c in save['cards']}
        print()
        print('卡组（%d 条非空 / 共 %d 个遭遇槽位）' % (len(dk['records']), dk['count']))
        for r in dk['records']:
            cells = []
            for s in r['cardSlots']:
                if s < 0:
                    cells.append('-')
                else:
                    c = byid.get(s)
                    cells.append((c['nameSimplified'] or c['nameEnglish'])
                                 if c else str(s))
            print('  遭遇 #%-4d %s  已指派=%d' % (r['index'], ' | '.join(cells), r['flag']))
    ba = save['bonusAreas']
    named = [b for b in ba if b.get('recipeIdStr')]
    print('已解锁的配方加成区域: %d 个（%d 个能对上配方表）' % (len(ba), len(named)))
    print('剧情进度: %d 条记录' % len(save['storyProgress']))
    grids = save['hexGrids']
    filled = [g for g in grids if g['filledCount']]
    print('六边形网格: %d 段（其中 %d 段有填充）' % (len(grids), len(filled)))
    if args.grids:
        print()
        print('%-10s %-7s %-7s %s' % ('偏移', '格子数', '已填', '填充的格子 (Q,R,S)=值'))
        for g in sorted(grids, key=lambda x: -x['filledCount']):
            cells = g['cells'] or []
            shown = ' '.join('(%d,%d,%d)=%d' % (c['q'], c['r'], c['s'], c['fill'])
                             for c in cells if c['fill'])[:150]
            print('  %#08x %-7d %-7d %s' % (g['offset'], g['cellCount'],
                                            g['filledCount'], shown or '(无)'))
    print('配方 id（已解锁）: %s' % ', '.join(save['recipeIds'][:12]))
    iotas = save['iotas']
    if iotas:
        print('粒子库存: %d 堆 / 共 %d 个（数组 @%#x, %d 槽位）' % (
            iotas['used'], iotas['total'], iotas['base'], iotas['slots']))
        if args.iotas:
            print()
            print('%-10s %-10s %-5s %-6s %s'
                  % ('偏移', '粒子', '效力', '数量', '特性'))
            for s in sorted(iotas['stacks'], key=lambda x: -x['count']):
                names = [n or str(i) for i, n in zip(s['traitIds'],
                                                     s['traitNames'])]
                trtxt = ' / '.join(names) or '-'
                print('  %#08x %-10s %-5d %-6d %s'
                      % (s['offset'], s['baseIotaName'] or s['baseIotaId'],
                         s['potency'], s['count'], trtxt))
            agg = {}
            for s in iotas['stacks']:
                k = s['baseIotaName'] or s['baseIotaId']
                agg[k] = agg.get(k, 0) + s['count']
            print('  按种类合计: %s' % ', '.join(
                '%s=%d' % kv for kv in sorted(agg.items(), key=lambda x: -x[1])[:12]))
    print('字符串总数: %d' % len(save['strings']))

    out = resolve_write_path(args.json or DEFAULT_JSON)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_json(save),
                   encoding='utf-8')
    print('\n已导出 JSON: %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
