from wh3_ally_inspect import *
from scan_mods import discover, enabled, read_rows, keyed_rows, EFFECT_TABLES
from landmark_effects import LandmarkEffects
import hashlib
from collections import Counter
from collections import defaultdict
from functools import lru_cache
from uuid import uuid5,NAMESPACE_DNS
get=lru_cache(None)(get)
extra,origins,rewards = discover()
@lru_cache(None)
def rows(t):
 base=get(t)[1]
 if t in EFFECT_TABLES:
  return list(keyed_rows(t,extra[t]+base).values())
 return base+extra[t] if t in extra else base
def group(t,key):
 d=defaultdict(list)
 for r in rows(t):d[r[key]].append(r)
 return d
prefix='alm9_'
output=defaultdict(list)
strings={}
def add(table,**r):output[table].append(r)
def clone(table,r,**fields):add(table,**(r|fields))
def enc(ft,v):
 if ft.startswith('Optional'):return b'\0' if v is None else b'\1'+enc(ft[8:],v)
 if ft.startswith('String'):
  wide=ft.endswith('16'); b=v.encode('utf-16le' if wide else 'utf8');return struct.pack('<H',len(b)//(2 if wide else 1))+b
 return struct.pack('<'+{'Boolean':'B','I32':'i','I64':'q','F32':'f'}[ft],v)
regions={r['region'].split('_region_')[-1]:r['region'] for r in rows('campaign_map_regions') if '_combi_region_' in r['region']}
iee_regions={}
for path in enabled():
 if 'immortal_empires_expanded' not in path.name.lower():continue
 pack=index(path)
 try:
  for r in read_rows(pack,'campaign_map_regions'):
   if r['campaign_map']=='cr_combi_expanded_map_1' and '_region_' in r['region']:
    iee_regions[r['region'].split('_region_',1)[1]]=r['region']
 finally:pack[0].close()
regions.update(iee_regions)
allowed_sets={r['chain_set'] for r in rows('slot_template_permitted_building_chains') if not r['remove']}
chains={r['key']:r for r in rows('building_chains')}
levels=group('building_levels','chain'); effects=group('building_effects_junction','building')
availability=group('building_chain_availability_sets','building_chain')
rules=group('building_chain_availabilities','set_id')
benefits=LandmarkEffects(rows,add,strings)
variants=group('building_culture_variants','building')
prereqs=group('building_level_required_buildings','building_level')
garrisons=group("building_level_armed_citizenry_junctions","building_level")
garrison_ids={r["id"] for r in rows("building_level_armed_citizenry_junctions")}
instances={r['key']:r for r in rows('building_instances')}
copied_instances=set()
landmark_set='wh2_main_set_landmark'
native_landmarks={r['building_chain'] for r in rows('building_set_to_building_junctions')
                  if r['building_set']==landmark_set and not r['exclude']}
superchains=group('building_chains','building_superchain')
done={}; kept_effects=0
def prepare(chain):
 global kept_effects
 if chain in done:return done[chain]
 done[chain]=False
 lv=levels[chain]
 if not any(rule['campaign'] in (None,'wh3_main_combi','cr_combi_expanded') for a in availability[chain] for rule in rules[a['id']]) or not lv or any(prereqs[x['level_name']] or not x['visible_in_ui'] for x in lv):return False
 translated={}
 for x in lv:
  b=x['level_name']
  translated[b]=[mapped for row in effects[b] for mapped in benefits.translate(row)]
  if not translated[b] and not garrisons[b] and b not in rewards:return False
 done[chain]=True
 # A separate superchain keeps the foreign copy out of domestic template sets.
 add('building_superchains',key=prefix+chain)
 clone('building_chains',chains[chain],key=prefix+chain,building_superchain=prefix+chain,is_foreign_slot_chain=1,in_encyclopedia=0)
 # The foreign construction popup enumerates visible building sets first.
 add('building_set_to_building_junctions',building_chain=prefix+chain,building_level=None,
     building_set=landmark_set,exclude=0)
 for a in availability[chain]:clone('building_chain_availability_sets',a,building_chain=prefix+chain)
 for x in lv:
  b=x['level_name']
  # Several native variants share an instance record. Keep that relationship
  # among foreign variants without consuming the domestic landmark's allowance.
  instance=x.get('building_instance_key')
  foreign_instance=None
  if instance in instances:
   foreign_instance=prefix+instance
   if instance not in copied_instances:
    clone('building_instances',instances[instance],key=foreign_instance)
    copied_instances.add(instance)
  clone('building_levels',x,level_name=prefix+b,chain=prefix+chain,building_instance_key=foreign_instance,first_in_world_bundle=None,can_convert=0,only_in_capital=0)
  for r in garrisons[b]:
   new_id=int.from_bytes(hashlib.sha256((b+'|'+r['unit_group']+'|'+str(r['id'])).encode()).digest()[:7],'little')
   assert new_id not in garrison_ids
   garrison_ids.add(new_id)
   clone('building_level_armed_citizenry_junctions',r,building_level=prefix+b,id=new_id)
  for r in variants[b]:clone('building_culture_variants',r,building=prefix+b)
  seen=set()
  for row in translated[b]:
   key=(row['effect'],row['effect_scope'],row['context_requirement'])
   if key not in seen:
    clone('building_effects_junction',row,building=prefix+b)
    seen.add(key)
    kept_effects+=1
 return True
sites=defaultdict(set)
for r in rows('building_chain_set_items'):
 s=r['set']
 if '_addon_landmark_' not in s or s not in allowed_sets or r['remove'] or not r['chain']:continue
 name=s.split('_addon_landmark_')[1]
 name={'tower_of_hoeth':'white_tower_of_hoeth'}.get(name,name)
 if name in regions and prepare(r['chain']):sites[regions[name]].add(r['chain'])
# Link direct mod entries to named settlement templates. A template that grants
# a known landmark set is stronger evidence than a template name.
template_regions=defaultdict(set)
for r in get('slot_template_permitted_building_chains')[1]:
 name=(r['chain_set'] or '').partition('_addon_landmark_')[2]
 name={'tower_of_hoeth':'white_tower_of_hoeth'}.get(name,name)
 if name in regions and not r['remove']:template_regions[r['slot_template']].add(regions[name])
for r in rows('slot_template_permitted_building_chains'):
 if r['remove']:continue
 if r['chain']:
  candidates=[r['chain']] if r['chain'] in origins or r['chain'] in native_landmarks else []
 else:
  candidates=[c['key'] for c in superchains.get(r['super_chain'],[]) if c['key'] in native_landmarks and c['key'] not in origins]
 if not candidates:continue
 template=r['slot_template']
 targets=template_regions[template]
 if not targets:
  match=re.fullmatch(r'(?:wh[\w]*?_special_(.+?)_secondary(?:_\w+)?|cr_(?:minor|major)_secondary_(.+)|mixer_ime_(?:minor|major)_secondary_(.+))',template)
  if match:
   name=next(x for x in match.groups() if x)
   if name not in regions and template.startswith('mixer_ime_'):
    name=next((k for k in sorted(regions,key=len,reverse=True) if name.endswith('_'+k)),None)
   if name in regions:targets={regions[name]}
 if len(targets)==1:
  for candidate in candidates:
   if candidate in chains and prepare(candidate):sites[next(iter(targets))].add(candidate)
add('slot_set_types',key='ALM9_LANDMARK')
for feat in ['region_owner_cannot_remove','remove_when_at_war','allow_allied_outpost_construction','grant_allied_region_owner_armed_citizenry','grant_neutral_region_owner_armed_citizenry']:
 add('slot_set_type_feature_junctions',feature=feat,slot_set_type='ALM9_LANDMARK')
def lua_s(v):return '"'+v+'"' if v else 'false'
lua=['local landmark_regions = {']; ids={r['id'] for r in rows('slot_set_items')}
tool_dir=Path(__file__).resolve().parent
legacy={key:7380019000+i for i,key in enumerate((tool_dir/'base_slots.txt').read_text().splitlines())}
for region,cs in sorted(sites.items()):
 site=prefix+region
 add('slot_templates',key=site,resource=None)
 add('slot_sets',key=site,type='ALM9_LANDMARK',composite_scene=None,non_owner_composite_scene=None)
 slot_id=legacy.get(region, int.from_bytes(hashlib.sha256(region.encode()).digest()[:7],'little'))
 assert slot_id not in ids
 ids.add(slot_id)
 add('slot_set_items',id=slot_id,slot_template=site,slot_set=site,slot_type='foreign',building_level=None)
 cond=set()
 for c in sorted(cs):
  add('slot_template_permitted_building_chains',chain=prefix+c,chain_set=None,remove=0,slot_template=site,super_chain=None)
  for a in availability[c]:
   for r in rules[a['id']]:
    if r['campaign'] in (None,'wh3_main_combi','cr_combi_expanded'):cond.add('{'+','.join(lua_s(r[k]) for k in ('culture','sub_culture','faction'))+'}')
 lua.append('    ["'+region+'"] = {key = "'+site+'", rules = {'+','.join(sorted(cond))+'}},')
lua.append('}')
level_keys={r['level_name'][len(prefix):] for r in output['building_levels']}
for r in rows('building_upgrades_junction'):
 if r['from'] in level_keys and r['to'] in level_keys:clone('building_upgrades_junction',r,**{k:prefix+v for k,v in r.items()})
# Native localisation references resolve to the player's installed game language.
for building in level_keys:
 name='building_culture_variants_name_'
 strings[name+prefix+building]='盟约 · {{tr:'+name+building+'}}'
for r in output['building_culture_variants']:
 suffix=''.join(r[k] or '' for k in ('culture','subculture','faction'))
 old=r['building'][len(prefix):]+suffix
 strings['building_culture_variants_name_'+prefix+old]='盟约 · {{tr:building_culture_variants_name_'+old+'}}'
for chain in (k for k,v in done.items() if v):
 for name in ('building_chains_chain_tooltip_','building_chains_encyclopedia_name_'):
  strings[name+prefix+chain]='{{tr:'+name+chain+'}}'
lua.append('local allied_outposts = {')
for r in rows('slot_sets'):
 if r['type']=='ALLIED':lua.append('    ["'+r['key']+'"] = true,')
lua.append('}')
lua.append('local landmark_rewards = {')
reward_count=0
for building,(flag,item,show) in sorted(rewards.items()):
 if building in level_keys:
  lua.append('    ["'+prefix+building+'"] = {flag="'+flag+'", item="'+item+'", silent='+show+'},')
  reward_count+=1
lua.append('}')
lua.extend(benefits.host_script(level_keys))
files={}
target=tool_dir.parent
lua_path=target/'allied_landmarks.lua'
lua_text='\n'.join(lua)+'\n\n'+(tool_dir/'wh3_grant.lua').read_text(encoding='utf8')
files[r'script\campaign\mod\allied_landmarks.lua']=lua_text.encode("utf8")
for t,rs in output.items():
 fields,_,hdr=get(t)
 layouts={tuple(r) for r in rs}
 for layout in layouts:
  missing=set(dict(fields))-set(layout)
  if missing:print(t,'missing',missing)
  assert missing <= {'override_startpos_settlement_display_building','context_requirement','building_frame_override','split_chain_sort_order','resource_transaction_on_complete','always_show_display_text'},(t,missing)
 for r in rs:
  if len(r)!=len(fields):
   for k,ft in fields:
    if k not in r:r[k]={'override_startpos_settlement_display_building':0,'context_requirement':'','building_frame_override':None,'split_chain_sort_order':-1,'resource_transaction_on_complete':None,'always_show_display_text':0}[k]
 assert len(set(tuple(r.items()) for r in rs))==len(rs),t
 hdr=hdr[:6]+str(uuid5(NAMESPACE_DNS,'alm9.'+t)).encode('utf-16le')+hdr[78:]
 files['db\\'+t+'_tables\\alm9_landmarks']=hdr+struct.pack('<I',len(rs))+b''.join(enc(ft,r[k]) for r in rs for k,ft in fields)
files[r'text\db\alm9_landmarks.loc']=b'\xff\xfeLOC\0'+struct.pack('<II',1,len(strings))+b''.join(enc('StringU16',k)+enc('StringU16',v)+b'\0' for k,v in sorted(strings.items()))
idx=b''.join(struct.pack('<IB',len(b),0)+k.encode()+b'\0' for k,b in files.items())
pack=target/'allied_landmarks.pack';pending=pack.with_suffix('.pending');pending.write_bytes(struct.pack('<4s6I',b'PFH5',3,0,0,len(files),len(idx),0)+idx+b''.join(files.values()))
test=index(pending)
assert all(extract(test,k)==v for k,v in files.items())
test[0].close(); pending.replace(pack); lua_path.write_text(lua_text,encoding="utf8")
print('adapted mods',Counter(origins[k] for k,v in done.items() if v and k in origins),'items',reward_count,'IEE-only regions',sum(r.startswith('cr_') for r in sites),'garrison rows',len(output['building_level_armed_citizenry_junctions']))
print('regions',len(sites),'chains',sum(done.values()),'levels',len(level_keys),'effects',kept_effects,'names',len(strings),'size',pack.stat().st_size)
for city in ('altdorf','nuln','white_tower_of_hoeth'):
 print(city,sites[regions[city]])
