"""Route foreign-building effects using DB relationships, retaining original target filters."""
from collections import defaultdict
from hashlib import sha256
import json
import re

from scan_mods import FILTER_TABLES, RECRUIT_TABLES


def record_key(kind, *parts):
    digest = sha256('|'.join(parts).encode()).hexdigest()[:24]
    return f'alm9_{kind}_{digest}'


class LandmarkEffects:
    def __init__(self, rows, add, strings):
        self.add = add
        self.strings = strings
        self.scopes = {r['key']: r for r in rows('campaign_effect_scopes')}
        self.conditions = {r['key']: r for r in rows('building_effect_context_expressions')}
        self.filters = defaultdict(list)
        for table in FILTER_TABLES:
            for row in rows(table):
                self.filters[row['campaign_effect_scope_key']].append((table, row))

        # These IDs describe existing recruitment bonuses. Unlocks and faction caps
        # have different semantics, even when they refer to the same hero or unit.
        recruit_ids = {'recruitment_level', 'recruit_cost_mod', 'unit_xp_mod',
                       'cost_mod', 'recruit_time_mod', 'recruit_time_mod_land',
                       'recruitment_mod_cost_land_all', 'recruitment_points'}
        self.recruitment = {r['effect'] for t in RECRUIT_TABLES for r in rows(t)
                            if r['bonus_value_id'] in recruit_ids}
        self.hero_caps = {r['effect'] for table in ('effect_bonus_value_agent_junction',
                                                  'effect_bonus_value_agent_subtype_junctions')
                          for r in rows(table) if r['bonus_value_id'] == 'cap'}
        resources = {r['key'] for r in rows('pooled_resources') if r['scope'] == 'FACTION'}
        factors = {r['unique_id'] for r in rows('pooled_resource_factor_junctions')
                   if r['resource'] in resources}
        self.resources = {r['effect'] for r in rows('effect_bonus_value_pooled_resource_factor_junctions')
                          if r['resource_factor'] in factors}
        self.resources.update(r['effect'] for r in rows('effect_bonus_value_pooled_resource_junctions')
                              if r['pooled_resource'] in resources)
        self.created = set()
        self.markers = {}
        self.level_markers = defaultdict(set)
        self.blank = next(r for r in rows('effects') if r['effect'] == 'blank_effect')

    def scope(self, original, source, location, label):
        key = record_key(source, original['key'], location)
        if key not in self.created:
            self.created.add(key)
            self.add('campaign_effect_scopes', **(original | dict(key=key, source=source, location=location)))
            for table, row in self.filters[original['key']]:
                self.add(table, **(row | {'campaign_effect_scope_key':key}))
            self.strings['campaign_effect_scopes_localised_text_'+key] = label
        return key

    def condition(self, original, host=False):
        row = self.conditions.get(original)
        if not row:
            return original
        # Only reinterpret simple identity predicates. Leave mixed geographical,
        # quest and technology expressions intact.
        expression = row['expression']
        term = r'(?:Region\.)?Owner\.(?:CultureKey|SubcultureKey|FactionKey|Key)\s*(?:==|!=)\s*"\w+"'
        if not re.fullmatch(rf'\s*{term}(?:\s*(?:\|\||&&)\s*{term})*\s*', expression):
            return original
        owner = 'Region.Owner.' if host else 'Owner.'
        changed = re.sub(r'(?:Region\.)?Owner\.', owner, expression)
        if changed == expression:
            return original
        key = record_key('condition', original, owner)
        if key not in self.created:
            self.created.add(key)
            self.add('building_effect_context_expressions', **(row | dict(key=key, expression=changed)))
        return key

    def host_marker(self, row, scope):
        # Let the building system evaluate conditions and intact/damaged/ruined
        # values. Lua reads the resulting regional scripted bonus, not the tooltip.
        marker = record_key('signal', row['effect'], scope)
        if marker not in self.markers:
            self.markers[marker] = (row['effect'], scope)
            self.add('effects', **(self.blank | dict(effect=marker, priority=0)))
            self.add('scripted_bonus_value_ids', key=marker)
            self.add('effect_bonus_value_scripted_junctions', effect=marker,
                     bonus_value_id='value', scripted_record=marker)
        self.level_markers[row['building']].add(marker)
        return row | dict(effect=marker, effect_scope='foreign_building_to_region_own',
                          context_requirement=self.condition(row['context_requirement'], host=True))

    def translate(self, row):
        scope = self.scopes.get(row['effect_scope'])
        if not scope or scope['ownership'] != 'yours':
            return []
        target, location = scope['target'], scope['location']
        builder_condition = self.condition(row['context_requirement'])
        def builder(new_scope):
            return row | dict(effect_scope=new_scope, context_requirement=builder_condition)

        if (row['effect'] in self.resources and target in ('building','faction')
                and location in ('buildingwide','factionwide') and scope['territory']=='any'
                and not self.filters[scope['key']]):
            return [builder('foreign_building_to_faction_own_unseen')]
        if (row['effect'] in self.hero_caps and target in ('province','region','faction')
                and scope['territory']=='any' and not self.filters[scope['key']]):
            return [builder('foreign_building_to_faction_own_unseen')]
        if location == 'factionwide' and target in ('faction','province','region','army','force','character'):
            return [builder(self.scope(scope,'foreign_building',location,'（建设者派系范围）'))]
        if location not in ('regionwide','provincewide','provincewide_geographical'):
            return []
        mobile = target in ('character','character_when_commanding','character_when_commanding_no_colonel','army','force')
        recruit = row['effect'] in self.recruitment and target in ('province','region')
        if mobile or recruit:
            area = 'regionwide' if location == 'regionwide' else 'provincewide_geographical'
            # Recruitment in a province is attached to each side's own settlements.
            # For the host the landmark region already belongs to that faction-province.
            host_area = 'provincewide' if recruit and area != 'regionwide' else area
            own = self.scope(scope, 'foreign_building', area, '（建设者在当地）')
            host = self.scope(scope, 'region', host_area, '（城主在当地）')
            return [builder(own), self.host_marker(row,host)]
        if scope['territory']=='any' and not self.filters[scope['key']]:
            if (target,location) in {('province','provincewide'),('region','regionwide')}:
                dest = 'foreign_building_to_province' if target=='province' else 'foreign_building_to_region_own'
                return [row | dict(effect_scope=dest, context_requirement=self.condition(row['context_requirement'],host=True))]
        return []

    def host_script(self, levels):
        active = {b:sorted(self.level_markers[b]) for b in sorted(levels) if self.level_markers.get(b)}
        used = sorted({m for markers in active.values() for m in markers})
        self.add('effect_bundles', key='alm9_host_local', localised_description='', localised_title='',
                 bundle_target='region', priority=0, ui_icon='', is_global_effect=1, show_in_3d_space=0, owner_only=1)
        lines = ['local host_values = {']
        for m in used:
            effect, scope = self.markers[m]
            lines.append(f'    [{json.dumps(m)}] = {{{json.dumps(effect)}, {json.dumps(scope)}}},')
        lines.append('}\nlocal host_buildings = {')
        for b, markers in active.items():
            values = ', '.join(map(json.dumps,markers))
            lines.append(f'    [{json.dumps("alm9_"+b)}] = {{{values}}},')
        lines.append('}')
        print('Shared effects:',len(used),'building levels with sharing:',len(active))
        return lines
