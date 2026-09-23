"""用 In Falsus Resource 导出的 4 个 JSON，生成工具需要自带的 5 张表"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = ('songs.json', 'dynamic_string_mapping.json',
       'recipe_specifications.json', 'story_details.json')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(name, obj):
    (HERE / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                             encoding='utf-8')
    print('  -> %s' % name)


def main():
    missing = [n for n in SRC if not (HERE / n).is_file()]
    if missing:
        print('缺少文件: %s' % ', '.join(missing))
        return 1

    rec = load(HERE / 'recipe_specifications.json')
    sd = load(HERE / 'story_details.json')

    # 粒子类型表：从配方表的 sparseIotas 抽出来
    write('iota_table.json', {'CommitId': rec.get('CommitId'),
                              'sparseIotas': rec.get('sparseIotas') or []})

    # 故事 id -> 条目下标
    smap = {}
    for i, e in enumerate(sd.get('orderedStoryEntries') or []):
        v = (e.get('StoryIdentifier') or {}).get('underlyingValue')
        if v is not None:
            smap[str(v)] = i
    write('story_id_map.json', smap)

    # 加成区域 GUID -> 配方
    amap = {}
    for r in rec.get('sparseRecipes') or []:
        if not r.get('IdStr'):
            continue
        for ai, area in enumerate(r.get('BonusAreas') or []):
            g = area.get('Id')
            if isinstance(g, str) and g:
                amap[g] = {'recipeIdStr': r['IdStr'],
                           'recipeName': r.get('Name') or '',
                           'recipeId': (r.get('Id') or {}).get('Value'),
                           'areaIndex': ai,
                           'cells': len(area.get('Cells') or []),
                           'effects': len(area.get('BonusEffects') or [])}
    write('bonus_area_map.json', amap)
    print('完成：%d 种粒子 / %d 个故事 id / %d 个加成区域'
          % (len(rec.get('sparseIotas') or []) - 1, len(smap), len(amap)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
