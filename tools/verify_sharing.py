"""Check destination ownership, radius and DB links in the generated mod."""
from pathlib import Path
import re

from scan_mods import index, read_rows, extract


def verify(path):
    pack = index(path)
    try:
        lua = extract(pack, r'script\campaign\mod\allied_landmarks.lua').decode()
        scopes = {r['key']: r for r in read_rows(pack, 'campaign_effect_scopes')}
        entries = read_rows(pack, 'building_effects_junction')
        signals = {r['effect'] for r in entries if r['effect'].startswith('alm9_signal_')}
        hosts = dict(re.findall(r'\["(alm9_signal_\w+)"\] = \{"[^"]+", "(alm9_region_\w+)"\}', lua))
        assert signals == hosts.keys()
        for scope_key in hosts.values():
            scope = scopes[scope_key]
            assert scope['ownership'] == 'yours' and scope['source'] == 'region'
            assert scope['location'] in ('regionwide','provincewide','provincewide_geographical')
        assert len({(r['building'],r['effect']) for r in entries}) == len(entries)
        for row in entries:
            if row['effect'] in signals:
                assert row['effect_scope'] == 'foreign_building_to_region_own'
        # Multi-choice foreign slots use PossibleBuildingSetList before listing chains.
        levels = read_rows(pack, 'building_levels')
        chains = {r['chain'] for r in levels}
        visible = {r['building_chain'] for r in read_rows(pack,'building_set_to_building_junctions')
                   if r['building_set']=='wh2_main_set_landmark' and not r['exclude']}
        assert visible == chains
        instances = {r['key']:r['num_instances'] for r in read_rows(pack,'building_instances')}
        assert all(r['building_instance_key'] in instances for r in levels if r['building_instance_key'])
        sites = {(r['slot_template'],r['chain']) for r in read_rows(pack,'slot_template_permitted_building_chains')}
        for city, chain in [('hexoatl','wh3_dlc24_cth_special_jade_dragon_astromantic_relay'),
                            ('hexoatl','wh2_main_special_hexoatl_stellar_pyramids_other'),
                            ('hexoatl','coffee_field'), ('hexoatl','Chasslo_YuanBo_Star_Chambers'),
                            ('fallen_gates','Heim_conquered_gates')]:
            key='alm9_'+chain
            if chain.startswith('wh') or key in chains:
                assert ('alm9_wh3_main_combi_region_'+city,key) in sites
                assert all(instances[r['building_instance_key']] >= 1 for r in levels if r['chain']==key and r['building_instance_key'])
        gates = [r for r in levels if r['level_name']=='alm9_Heim_conquered_gates']
        if gates:
            assert instances[gates[0]['building_instance_key']] == 1
        # Concrete regression from Chasslo IEE when present in this profile.
        red = {r['effect']:r for r in entries if r['building']=='alm9_Chasslo_IEE_redgrass'}
        if red and 'wh2_dlc09_pooled_resource_canopic_jars_buildings' in red:
            jar = red['wh2_dlc09_pooled_resource_canopic_jars_buildings']
            assert jar['effect_scope'] == 'foreign_building_to_faction_own_unseen'
            conditions = {r['key']:r['expression'] for r in read_rows(pack,'building_effect_context_expressions')}
            assert conditions[jar['context_requirement']]=='Owner.CultureKey == "wh2_dlc09_tmb_tomb_kings"'
            xp = red['wh2_dlc09_effect_agent_recruitment_xp_tmb_tomb_prince']
            assert scopes[xp['effect_scope']]['location'] == 'provincewide_geographical'
            assert xp['context_requirement']==jar['context_requirement']
            host_id=next(r for r in red if r in hosts and red[r]['context_requirement']=='IsRegionTombKing')
            assert scopes[hosts[host_id]]['target']=='province'
        print(f'Checked {len(signals)} shared effects and {len(entries)} unique building/effect bindings')
    finally:
        pack[0].close()


if __name__ == '__main__':
    verify(Path(__file__).resolve().parents[1]/'allied_landmarks.pack')
