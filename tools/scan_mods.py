"""Discover new building chains placed in named cities by the last launched mod list."""
from collections import defaultdict
from pathlib import Path
from functools import lru_cache
import re
from wh3_ally_inspect import D, S, decode, extract, get, index

# Import only rows belonging to a new chain defined by the source pack.
FIELDS = {
    'building_chains':'key', 'building_levels':'chain', 'building_chain_availability_sets':'building_chain',
    'building_culture_variants':'building', 'building_effects_junction':'building',
    'building_level_armed_citizenry_junctions':'building_level', 'building_level_required_buildings':'building_level',
    'building_upgrades_junction':'from', 'slot_template_permitted_building_chains':'chain',
    'building_chain_set_items':'chain',
}
def enabled():
    text=(D.parent/'used_mods.txt').read_text(encoding='utf-8-sig')
    paths=[Path(p) for p in re.findall(r'^add_working_directory "([^"]+)";', text, re.M)]
    for name in re.findall(r'^mod "([^"]+)";',text,re.M):
        if name.lower()=='allied_landmarks.pack':continue
        found=next((p/name for p in [*paths,D] if (p/name).is_file()),None)
        if found:yield found

def read_rows(pack,table):
    rows=[]
    for key in pack[1]:
        if key.startswith('db\\'+table+'_tables\\'):
            rows.extend(decode(table,extract(pack,key))[1])
    return list(keyed_rows(table,rows).values())

@lru_cache(None)
def table_keys(table):
    definition=S.split('        "'+table+'_tables": [',1)[1].split('localised_fields:',1)[0]
    return re.findall(r'name: "([^"]+)",\s+field_type: \w+,\s+is_key: true',definition)

def keyed_rows(table, rows):
    distinct={}
    if not rows:return distinct
    keys=table_keys(table) or list(rows[0])
    for row in rows:
        distinct.setdefault(tuple(row.get(k) for k in keys),row)
    return distinct

def item_rules(script):
    # Recognize only the complete, unconditional, once-per-campaign award idiom.
    # Additional checks, rolls or side effects require a hand-written adapter.
    script=re.sub(r'--[^\n]*','',script)
    key=r'"([\w]+)"'
    event=(r'core:add_listener\s*\(\s*"[\w]+"\s*,\s*"BuildingCompleted"\s*,\s*function\(context\)(.*?)end\s*,'
           r'\s*function\(context\)(.*?)end\s*,\s*true\s*\)')
    for condition,body in re.findall(event,script,re.S):
        def strip_locals(part):
            return re.sub(r'\blocal\s+(?:building\s*=\s*context:building\(\)|faction\s*=\s*context:building\(\):region\(\):owning_faction\(\)|faction_name\s*=\s*context:building\(\):region\(\):owning_faction\(\):name\(\)|faction\s*=\s*cm:get_faction\(faction_name\))\s*;?', '',part).strip()
        cond=re.fullmatch(r'return\s+cm:get_saved_value\('+key+r'\)\s*==\s*nil\s+and\s+building:name\(\)\s*==\s*'+key+r'\s*;?',strip_locals(condition))
        award=re.fullmatch(r'cm:add_ancillary_to_faction\s*\(\s*faction\s*,\s*'+key+r'\s*,\s*(true|false)\s*\)\s*;?\s*cm:set_saved_value\('+key+r'\s*,\s*true\)\s*;?',strip_locals(body))
        if cond and award and cond[1]==award[3]:yield cond[2],(cond[1],award[1],award[2])

FILTER_TABLES = (
    'campaign_effect_scope_agent_junctions',
    'campaign_effect_scope_character_force_relationship_junctions',
    'campaign_effect_scope_faction_set_junctions',
)
RECRUIT_TABLES = (
    'effect_bonus_value_agent_junction', 'effect_bonus_value_agent_subtype_junctions',
    'effect_bonus_value_ids_unit_sets', 'effect_bonus_value_basic_junction',
    'effect_bonus_value_unit_record_junctions',
)
EFFECT_TABLES = (
    'campaign_effect_scopes','building_effect_context_expressions','building_effects_junction',
    'building_instances','building_set_to_building_junctions','slot_template_permitted_building_chains',
    'pooled_resources','pooled_resource_factor_junctions',
    'effect_bonus_value_pooled_resource_factor_junctions','effect_bonus_value_pooled_resource_junctions',
    *FILTER_TABLES,*RECRUIT_TABLES,
)

def discover():
    extra=defaultdict(list); origins={}; rewards={}
    known={r['key'] for r in get('building_chains')[1]}
    for path in enabled():
        pk=index(path)
        try:
            for table in EFFECT_TABLES:
                extra[table].extend(read_rows(pk,table))
            extra['building_chain_availabilities'].extend(read_rows(pk,'building_chain_availabilities'))
            if not any(k.startswith(('db\\slot_template_permitted_building_chains_tables\\','db\\building_chain_set_items_tables\\')) for k in pk[1]):continue
            chains={r['key'] for r in read_rows(pk,'building_chains')}-known
            if not chains:continue
            rows={t:read_rows(pk,t) for t in FIELDS if t not in EFFECT_TABLES}
            levels={r['level_name'] for r in rows['building_levels'] if r['chain'] in chains}
            for t,data in rows.items():
                for r in data:
                    if r[FIELDS[t]] in (chains if t in ('building_chains','building_levels','building_chain_availability_sets','slot_template_permitted_building_chains','building_chain_set_items') else levels):
                        extra[t].append(r)
            origins.update(dict.fromkeys(chains,path.name))
            known.update(chains)
            for k in pk[1]:
                if k.endswith('.lua') and k.startswith('script\\campaign\\') and ('\\mod\\' in k):
                    rewards.update((b,reward) for b,reward in item_rules(extract(pk,k).decode('utf8', errors='replace')) if b in levels)
        finally:pk[0].close()
    return extra,origins,rewards
